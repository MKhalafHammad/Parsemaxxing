"use client";

import { ArrowDown, ArrowUp, CircleCheck, CircleX, Lock, Plus, Trash2, TriangleAlert, Upload } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { Field, FormError, PasswordField } from "@/components/auth/fields";
import { AdminOnly, useSession } from "@/components/auth/session";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/input";
import { Table, TBody, Td, Th, THead, Tr } from "@/components/ui/table";
import { api, ApiError, postJson, type Certificate, type GroupMode, type LdapConnection, type LdapLookup, type LdapSettings, type LdapView, type Role } from "@/lib/api";
import { when } from "@/lib/utils";

// The UI only shapes the request; the engine validates every field again (settings/groups.py).
type Draft = Omit<LdapSettings, "group_roles"> & { group_roles: { dn: string; role: Role }[] };
type Errors = Record<string, string>;

const SELECT = "h-9 rounded-md border border-line-strong bg-surface-solid px-2 text-sm";
const BOX = "h-4 w-4 accent-[var(--focus)]";
const ATTRIBUTE = /^[A-Za-z][A-Za-z0-9-]{0,63}$/;
const NAMES: Record<string, string> = {
  enabled: "Directory sign-in",
  servers: "Servers",
  ca_bundle: "CA bundle",
  bind_dn: "Bind DN",
  bind_password: "Bind password",
  user_search_base: "User search base",
  user_filter: "User filter",
  username_attribute: "User name attribute",
  display_name_attribute: "Display name attribute",
  group_mode: "Membership mode",
  group_search_base: "Group search base",
  nested_groups: "Nested groups",
  group_roles: "Group to role mapping",
  connect_timeout_seconds: "Connect timeout",
  read_timeout_seconds: "Read timeout",
  page_size: "Page size",
  require_mfa: "Require MFA for directory users",
  current_password: "Your password",
  session_max_hours: "Directory session length",
};
const MODES: { value: GroupMode; label: string; help: string }[] = [
  { value: "member_of", label: "memberOf on the user", help: "Reads the user's memberOf values. No group search base needed." },
  { value: "member", label: "member on the group", help: "Searches the group search base for groups whose member holds the user's DN." },
  { value: "ad_nested", label: "Active Directory nested groups", help: "Asks Active Directory for every group the user is in, directly or through other groups." },
];
const STEPS: Record<string, string> = { connect: "Connect (TCP)", tls: "TLS", certificate: "Certificate", bind: "Bind" };
const SOURCES: Record<string, string> = { default: "Default", platform: "Set at platform level", "environment variable": "Managed by environment variable" };
const roleWord = (r: string | null) => (r === "admin" ? "Admin" : r === "viewer" ? "Viewer" : "No role");

const toDraft = (s: LdapSettings): Draft => ({ ...s, group_roles: Object.entries(s.group_roles).map(([dn, role]) => ({ dn, role })) });
const fromDraft = (d: Draft): LdapSettings => ({ ...d, group_roles: Object.fromEntries(d.group_roles.map((g) => [g.dn.trim(), g.role])) });

/** Plain LDAP is refused (the engine refuses it too): ldaps://, or ldap:// with StartTLS. */
function serverError(url: string, startTls: boolean): string {
  const u = url.trim().toLowerCase();
  if (!u) return "Enter the server URL, for example ldaps://ldap.example.com:636.";
  if (u.startsWith("ldap://") && !startTls) return "Plain LDAP is refused. Use ldaps:// or turn on StartTLS.";
  if (u.startsWith("ldaps://") && startTls) return "ldaps:// is already TLS. Turn StartTLS off.";
  if (!/^ldaps?:\/\/[^/?#@\s]+\/?$/.test(u)) return "Use ldaps://host[:port] or ldap://host[:port] with StartTLS, nothing else.";
  return "";
}

function check(d: Draft, tried: boolean, reauth?: { bind: string | null; current: string }): Errors {
  const e: Errors = {};
  // Moving sign-in to other servers needs the bind password again and the admin's own password.
  if (reauth && tried) {
    if (!reauth.bind) e.bind_password = "Enter the bind password again: changing the servers needs it.";
    if (!reauth.current) e.current_password = "Enter your own password to confirm this change.";
  }
  d.servers.forEach((s, i) => {
    const err = serverError(s.url, s.start_tls);
    if (err && (tried || s.url.trim())) e[`servers.${i}`] = err; // an empty new row waits for Save
  });
  const f = d.user_filter;
  const rest = f.replaceAll("{username}", "");
  const n = (f.length - rest.length) / "{username}".length;
  if (!f.startsWith("(") || !f.endsWith(")") || n < 1 || n > 4 || /[{}]/.test(rest)) e.user_filter = "Use one parenthesised filter with {username} 1 to 4 times, for example (uid={username}).";
  if (!ATTRIBUTE.test(d.username_attribute)) e.username_attribute = "Use an attribute name: a letter, then letters, digits or '-'.";
  if (!ATTRIBUTE.test(d.display_name_attribute)) e.display_name_attribute = "Use an attribute name: a letter, then letters, digits or '-'.";
  const seen = new Set<string>();
  d.group_roles.forEach((g, i) => {
    const dn = g.dn.trim().toLowerCase();
    if (!dn) e[`group_roles.${i}`] = "Enter the group DN, or remove this row.";
    else if (seen.has(dn)) e[`group_roles.${i}`] = "This group is already mapped.";
    seen.add(dn);
  });
  const range = (k: "connect_timeout_seconds" | "read_timeout_seconds" | "page_size" | "session_max_hours", lo: number, hi: number, unit: string) => {
    if (!Number.isInteger(d[k]) || d[k] < lo || d[k] > hi) e[k] = `Use ${lo} to ${hi} ${unit}.`;
  };
  range("connect_timeout_seconds", 1, 60, "seconds");
  range("read_timeout_seconds", 1, 120, "seconds");
  range("page_size", 1, 5000, "entries");
  range("session_max_hours", 1, 24, "hours");
  return e;
}

/** "Invalid LDAP settings: servers.0: msg; user_filter: msg" → per-field errors; the rest stays on the form. */
function fieldErrors(err: ApiError): { fields: Errors; rest: string } {
  const fields: Errors = {};
  const m = /^Invalid LDAP settings: (.*)$/s.exec(err.message);
  if (!m) return { fields, rest: "" };
  let rest = "";
  for (const part of (m[1] ?? "").split("; ")) {
    const [, name = "", , index, msg = ""] = /^([a-z_]+)(\.(\d+))?[^:]*: (.*)$/s.exec(part) ?? [];
    if (name in NAMES) fields[index && name === "servers" ? `servers.${index}` : name] = msg;
    else rest = rest ? `${rest}; ${part}` : part;
  }
  return { fields, rest };
}

/** The engine's re-entry refusals (auth/routes.py), shown on the password they are about. */
function passwordField(err: ApiError): "bind_password" | "current_password" | null {
  if (err.status === 403 && /password is not correct/i.test(err.message)) return "current_password";
  if (err.status === 422 && /^Enter the bind password again/.test(err.message)) return "bind_password";
  if (err.status === 422 && /^Enter your own current password/.test(err.message)) return "current_password";
  return null;
}

const fid = (key: string) => `ldap-${key.replace(".", "-")}`;

export default function AuthenticationPage() {
  const { isAdmin } = useSession();
  return (
    <div className="grid max-w-4xl gap-6">
      <div>
        <h1 className="text-xl font-semibold">Authentication and LDAP</h1>
        <p className="text-sm text-muted">Platform setting: applies to every environment.</p>
      </div>
      {isAdmin ? (
        <LdapAdmin />
      ) : (
        <>
          <BreakGlass admins={null} />
          <section aria-labelledby="ldap-title" className="glass grid gap-3 p-4">
            <h2 id="ldap-title" className="text-base font-semibold">
              Directory sign-in (LDAP)
            </h2>
            {/* The engine shows LDAP settings to admins only (GET /auth/ldap). */}
            <p className="text-sm text-muted">Only admins can see the directory settings. Ask an admin to change how people sign in.</p>
            <div className="flex flex-wrap gap-3">
              <AdminOnly>
                <Button>Save</Button>
              </AdminOnly>
              <AdminOnly>
                <Button variant="outline">Test connection</Button>
              </AdminOnly>
            </div>
          </section>
        </>
      )}
    </div>
  );
}

function BreakGlass({ admins }: { admins: string[] | null }) {
  return (
    <p role="note" className="glass flex flex-wrap items-center gap-2 p-3 text-sm">
      <Lock aria-hidden className="h-4 w-4 text-muted" />
      Local accounts always work when the directory is down.
      {admins && (
        <>
          {" "}
          Local admins: {admins.length}.{" "}
          <Link href="/settings/users?source=local" className="underline underline-offset-2">
            Show local users
          </Link>
        </>
      )}
    </p>
  );
}

function LdapAdmin() {
  const [view, setView] = useState<LdapView | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [loadError, setLoadError] = useState<string | Error>("");
  const [password, setPassword] = useState<string | null>(null); // null: not being changed
  const [current, setCurrent] = useState("");
  const [tried, setTried] = useState(false);
  const [serverErrors, setServerErrors] = useState<Errors>({});
  const [saveError, setSaveError] = useState<string | Error>("");
  const [conflict, setConflict] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");

  const load = useCallback(() => {
    api<LdapView>("/auth/ldap").then((v) => {
      setView(v);
      setDraft(toDraft(v.settings));
      setPassword(null);
      setCurrent("");
      setConflict(false);
      setSaveError("");
      setServerErrors({});
      setTried(false);
    }, setLoadError);
  }, []);
  useEffect(load, [load]);

  if (loadError) return <FormError error={loadError} />;
  if (!view || !draft)
    return (
      <p aria-busy="true" className="text-sm text-muted">
        Loading…
      </p>
    );

  const next = fromDraft(draft);
  const changed = (Object.keys(next) as (keyof LdapSettings)[]).filter((k) => JSON.stringify(next[k]) !== JSON.stringify(view.settings[k]));
  const reauth = changed.includes("servers") ? { bind: password, current } : undefined;
  const live = check(draft, tried, reauth);
  const errors = { ...live, ...serverErrors };
  const dirty = changed.length > 0 || !!password;
  const readOnly = (k: string) => view.sources[k] === "environment variable";
  const source = (k: string) => SOURCES[view.sources[k] ?? "default"] ?? view.sources[k];
  const blocked = !view.settings.enabled && view.missing_for_enable.length > 0;

  const edit = (patch: Partial<Draft>) => {
    setDraft({ ...draft, ...patch });
    setServerErrors({});
    setMessage("");
  };
  const setServer = (i: number, patch: Partial<Draft["servers"][number]>) => edit({ servers: draft.servers.map((s, j) => (j === i ? { ...s, ...patch } : s)) });
  const move = (i: number, by: number) => {
    const s = [...draft.servers];
    s.splice(i + by, 0, ...s.splice(i, 1));
    edit({ servers: s });
  };
  const setGroup = (i: number, patch: Partial<Draft["group_roles"][number]>) => edit({ group_roles: draft.group_roles.map((g, j) => (j === i ? { ...g, ...patch } : g)) });

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setTried(true);
    setSaveError("");
    setMessage("");
    if (Object.keys(check(draft!, true, reauth)).length) return;
    if (!dirty) return setMessage("Nothing to save: no setting changed.");
    const body: Record<string, unknown> = { expected_version: view!.version };
    if (changed.length) body.settings = Object.fromEntries(changed.map((k) => [k, next[k]]));
    if (password) body.bind_password = password;
    if (reauth) body.current_password = current;
    setSaving(true);
    try {
      const v = await postJson<LdapView>("/auth/ldap", body, "PUT");
      setView(v);
      setDraft(toDraft(v.settings));
      setPassword(null); // the typed passwords leave the page once stored
      setCurrent("");
      setTried(false);
      setMessage("LDAP settings saved. New sign-ins use them.");
    } catch (err) {
      const onField = err instanceof ApiError ? passwordField(err) : null;
      if (onField) setServerErrors({ [onField]: (err as Error).message });
      else if (err instanceof ApiError && err.status === 409) setConflict(true);
      else if (err instanceof ApiError && err.status === 422) {
        const { fields, rest } = fieldErrors(err);
        setServerErrors(fields);
        setSaveError(Object.keys(fields).length && !rest ? "" : err);
      } else setSaveError(err as Error);
    } finally {
      setSaving(false);
    }
  }

  const shownErrors = tried || Object.keys(serverErrors).length ? Object.entries(errors) : [];
  const describe = (k: string, hint?: boolean) => ({
    "aria-invalid": errors[k] ? true : undefined,
    "aria-describedby": [hint && `${fid(k)}-hint`, errors[k] && `${fid(k)}-error`].filter(Boolean).join(" ") || undefined,
  });
  const err = (k: string) =>
    errors[k] ? (
      <p id={`${fid(k)}-error`} className="text-sm text-bad">
        {errors[k]}
      </p>
    ) : null;

  return (
    <>
      <BreakGlass admins={view.local_admins} />

      <form onSubmit={save} noValidate className="grid gap-6">
        {shownErrors.length > 0 && (
          <div role="alert" className="rounded-md border border-bad p-3 text-sm">
            <p className="font-semibold text-bad">Fix {shownErrors.length === 1 ? "this setting" : `these ${shownErrors.length} settings`} before saving:</p>
            <ul className="mt-1 list-disc pl-5">
              {shownErrors.map(([k, msg]) => (
                <li key={k}>
                  <a href={`#${fid(k)}`} className="underline underline-offset-2">
                    {NAMES[k.split(".")[0] ?? ""]}
                    {k.includes(".") && ` ${Number(k.split(".")[1]) + 1}`}
                  </a>
                  : {msg}
                </li>
              ))}
            </ul>
          </div>
        )}

        <section aria-labelledby="enable-title" className="glass grid gap-2 p-4">
          <h2 id="enable-title" className="text-base font-semibold">
            Directory sign-in (LDAP)
          </h2>
          <div className="flex items-center gap-2">
            <input
              id={fid("enabled")}
              type="checkbox"
              className={BOX}
              checked={draft.enabled}
              aria-disabled={blocked || undefined}
              aria-describedby={blocked ? "ldap-missing" : "ldap-enabled-hint"}
              onChange={(e) => !blocked && edit({ enabled: e.target.checked })}
            />
            <Label htmlFor={fid("enabled")}>Let directory users sign in</Label>
            <Badge variant={view.settings.enabled ? "good" : "default"} className="ml-2">
              {view.settings.enabled ? <CircleCheck aria-hidden className="h-3.5 w-3.5" /> : <CircleX aria-hidden className="h-3.5 w-3.5" />}
              {view.settings.enabled ? "On" : "Off"}
            </Badge>
          </div>
          {blocked ? (
            <div id="ldap-missing" className="text-sm text-warn">
              <p className="flex items-center gap-1">
                <TriangleAlert aria-hidden className="h-4 w-4" /> Can&apos;t turn on yet. Save these first:
              </p>
              <ul className="list-disc pl-6">
                {view.missing_for_enable.map((m) => (
                  <li key={m}>{NAMES[m] ?? m}</li>
                ))}
              </ul>
            </div>
          ) : (
            <p id="ldap-enabled-hint" className="text-[13px] text-subtle">
              Names that are not local accounts are checked against the directory. {source("enabled")}.
            </p>
          )}
        </section>

        <section aria-labelledby="servers-title" className="glass grid gap-3 p-4">
          <h2 id="servers-title" className="text-base font-semibold">
            Servers
          </h2>
          <p className="text-[13px] text-subtle">Tried in this order. LDAPS (port 636) or StartTLS only: plain LDAP is never used. The server&apos;s host name is always checked against its certificate.</p>
          {draft.servers.length === 0 && (
            <p className="text-sm text-muted">No servers yet. First-time setup: upload the CA bundle with the bind password (below), then add the servers here and save with the bind password and your own password.</p>
          )}
          <ol className="grid gap-3">
            {draft.servers.map((s, i) => (
              <li key={i} className="grid gap-1 rounded-md border border-line p-3">
                <div className="flex flex-wrap items-end gap-3">
                  <div className="grid min-w-64 flex-1 gap-1">
                    <Label htmlFor={fid(`servers.${i}`)}>Server {i + 1} URL</Label>
                    <input
                      id={fid(`servers.${i}`)}
                      value={s.url}
                      onChange={(e) => setServer(i, { url: e.target.value })}
                      placeholder="ldaps://ldap.example.com:636"
                      maxLength={300}
                      autoComplete="off"
                      spellCheck={false}
                      className="h-9 rounded-md border border-line-strong bg-surface-2 px-3 font-mono text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus"
                      {...describe(`servers.${i}`)}
                    />
                  </div>
                  <span className="flex h-9 items-center gap-2">
                    <input id={`${fid(`servers.${i}`)}-tls`} type="checkbox" className={BOX} checked={s.start_tls} onChange={(e) => setServer(i, { start_tls: e.target.checked })} />
                    <Label htmlFor={`${fid(`servers.${i}`)}-tls`}>StartTLS</Label>
                  </span>
                  <span className="flex gap-1">
                    <Button type="button" size="sm" variant="outline" aria-label={`Move server ${i + 1} up`} disabled={i === 0} onClick={() => move(i, -1)}>
                      <ArrowUp aria-hidden className="h-4 w-4" />
                    </Button>
                    <Button type="button" size="sm" variant="outline" aria-label={`Move server ${i + 1} down`} disabled={i === draft.servers.length - 1} onClick={() => move(i, 1)}>
                      <ArrowDown aria-hidden className="h-4 w-4" />
                    </Button>
                    <Button type="button" size="sm" variant="outline" aria-label={`Remove server ${i + 1}`} onClick={() => edit({ servers: draft.servers.filter((_, j) => j !== i) })}>
                      <Trash2 aria-hidden className="h-4 w-4" />
                    </Button>
                  </span>
                </div>
                {err(`servers.${i}`)}
              </li>
            ))}
          </ol>
          <Button type="button" variant="outline" size="sm" className="justify-self-start" disabled={draft.servers.length >= 10} onClick={() => edit({ servers: [...draft.servers, { url: "", start_tls: false }] })}>
            <Plus aria-hidden className="h-4 w-4" /> Add server
          </Button>
          {err("servers")}
        </section>

        <CaBundle
          certs={view.ca_bundle}
          version={view.version}
          reload={load}
          // The upload answers with the whole view: a fresh version and checklist; unsaved edits here stay.
          onUploaded={setView}
        />

        <section aria-labelledby="bind-title" className="glass grid gap-4 p-4">
          <h2 id="bind-title" className="text-base font-semibold">
            Service account
          </h2>
          <Field
            id={fid("bind_dn")}
            label="Bind DN"
            value={draft.bind_dn ?? ""}
            onChange={(e) => edit({ bind_dn: e.target.value || null })}
            placeholder="cn=parsemaxxing,ou=services,dc=example,dc=com"
            hint={`The account Parsemaxxing searches with. ${source("bind_dn")}.`}
            error={errors.bind_dn}
            readOnly={readOnly("bind_dn")}
            maxLength={1024}
            autoComplete="off"
            spellCheck={false}
            className="font-mono"
          />
          <div className="grid gap-1">
            <p className="text-sm font-medium">Bind password</p>
            <p className="flex flex-wrap items-center gap-2 text-sm">
              {view.bind_password_set ? (
                <Badge variant="good">
                  <CircleCheck aria-hidden className="h-3.5 w-3.5" /> Set
                </Badge>
              ) : (
                <Badge>
                  <CircleX aria-hidden className="h-3.5 w-3.5" /> Not set
                </Badge>
              )}
              {reauth ? null : password === null ? (
                <Button type="button" size="sm" variant="outline" onClick={() => setPassword("")}>
                  {view.bind_password_set ? "Change…" : "Set…"}
                </Button>
              ) : (
                <Button type="button" size="sm" variant="ghost" onClick={() => setPassword(null)}>
                  Keep the current password
                </Button>
              )}
            </p>
            {(password !== null || reauth) && (
              <div className="sm:max-w-sm" onChange={(e) => setPassword((e.target as HTMLInputElement).value)}>
                <PasswordField
                  id={fid("bind_password")}
                  label={reauth ? "Bind password (required)" : "New bind password"}
                  autoComplete="new-password"
                  hint={reauth ? "You changed the servers: enter the bind password again. Stored in the vault, never shown." : "Stored in the vault. It is never shown again, here or anywhere."}
                  error={errors.bind_password}
                />
              </div>
            )}
            {reauth && (
              <div className="sm:max-w-sm" onChange={(e) => setCurrent((e.target as HTMLInputElement).value)}>
                <PasswordField id={fid("current_password")} label="Your password (required)" autoComplete="current-password" hint="Confirms it is you changing where sign-in goes." error={errors.current_password} />
              </div>
            )}
          </div>
        </section>

        <section aria-labelledby="search-title" className="glass grid gap-4 p-4">
          <h2 id="search-title" className="text-base font-semibold">
            User search
          </h2>
          <Field
            id={fid("user_search_base")}
            label="User search base"
            value={draft.user_search_base ?? ""}
            onChange={(e) => edit({ user_search_base: e.target.value || null })}
            placeholder="ou=people,dc=example,dc=com"
            hint={`Users are searched under this DN. ${source("user_search_base")}.`}
            error={errors.user_search_base}
            readOnly={readOnly("user_search_base")}
            maxLength={1024}
            autoComplete="off"
            spellCheck={false}
            className="font-mono"
          />
          <Field
            id={fid("user_filter")}
            label="User filter"
            value={draft.user_filter}
            onChange={(e) => edit({ user_filter: e.target.value })}
            hint={`{username} is replaced by the name typed at sign-in, escaped, so it can't change the filter. Use it 1 to 4 times, for example (|(uid={username})(mail={username})). The filter must match exactly one entry. ${source("user_filter")}.`}
            error={errors.user_filter}
            readOnly={readOnly("user_filter")}
            maxLength={512}
            autoComplete="off"
            spellCheck={false}
            className="font-mono"
          />
          <div className="grid gap-4 sm:grid-cols-2">
            <Field
              id={fid("username_attribute")}
              label="User name attribute"
              value={draft.username_attribute}
              onChange={(e) => edit({ username_attribute: e.target.value })}
              list="ldap-attributes"
              hint={`uid, sAMAccountName or userPrincipalName. ${source("username_attribute")}.`}
              error={errors.username_attribute}
              readOnly={readOnly("username_attribute")}
              maxLength={64}
              autoComplete="off"
              spellCheck={false}
            />
            <datalist id="ldap-attributes">
              <option value="uid" />
              <option value="sAMAccountName" />
              <option value="userPrincipalName" />
            </datalist>
            <Field
              id={fid("display_name_attribute")}
              label="Display name attribute"
              value={draft.display_name_attribute}
              onChange={(e) => edit({ display_name_attribute: e.target.value })}
              hint={`Shown as the user's name. ${source("display_name_attribute")}.`}
              error={errors.display_name_attribute}
              readOnly={readOnly("display_name_attribute")}
              maxLength={64}
              autoComplete="off"
              spellCheck={false}
            />
          </div>
        </section>

        <section aria-labelledby="groups-title" className="glass grid gap-4 p-4">
          <h2 id="groups-title" className="text-base font-semibold">
            Groups and roles
          </h2>
          <div className="grid gap-1">
            <Label htmlFor={fid("group_mode")}>Membership mode</Label>
            <select
              id={fid("group_mode")}
              value={draft.group_mode}
              onChange={(e) => edit({ group_mode: e.target.value as GroupMode })}
              disabled={readOnly("group_mode")}
              className={SELECT}
              aria-describedby={`${fid("group_mode")}-hint`}
            >
              {MODES.map((m) => (
                <option key={m.value} value={m.value}>
                  {m.label}
                </option>
              ))}
            </select>
            <p id={`${fid("group_mode")}-hint`} className="text-[13px] text-subtle">
              {MODES.find((m) => m.value === draft.group_mode)?.help} {source("group_mode")}.
            </p>
          </div>
          {draft.group_mode !== "member_of" && (
            <Field
              id={fid("group_search_base")}
              label="Group search base"
              value={draft.group_search_base ?? ""}
              onChange={(e) => edit({ group_search_base: e.target.value || null })}
              placeholder="ou=groups,dc=example,dc=com"
              hint={`Groups are searched under this DN. ${source("group_search_base")}.`}
              error={errors.group_search_base}
              readOnly={readOnly("group_search_base")}
              maxLength={1024}
              autoComplete="off"
              spellCheck={false}
              className="font-mono"
            />
          )}
          {draft.group_mode === "member" && (
            <span className="flex items-center gap-2">
              <input id={fid("nested_groups")} type="checkbox" className={BOX} checked={draft.nested_groups} onChange={(e) => edit({ nested_groups: e.target.checked })} aria-describedby={`${fid("nested_groups")}-hint`} />
              <Label htmlFor={fid("nested_groups")}>Follow groups inside groups</Label>
              <span id={`${fid("nested_groups")}-hint`} className="text-[13px] text-subtle">
                Up to 8 levels.
              </span>
            </span>
          )}

          <div className="grid gap-2">
            <h3 className="text-sm font-semibold">Group to role mapping</h3>
            <p className="text-[13px] text-subtle">No mapped group means no access. A user in more than one mapped group gets the highest role.</p>
            {draft.group_roles.length === 0 ? (
              <p className="text-sm text-muted">No groups mapped yet. Add the group whose members should sign in.</p>
            ) : (
              <Table aria-label="Group to role mapping">
                <THead>
                  <Tr>
                    <Th scope="col">Group DN</Th>
                    <Th scope="col">Role</Th>
                    <Th scope="col">
                      <span className="sr-only">Actions</span>
                    </Th>
                  </Tr>
                </THead>
                <TBody>
                  {draft.group_roles.map((g, i) => (
                    <Tr key={i}>
                      <Td className="w-full">
                        <input
                          id={fid(`group_roles.${i}`)}
                          aria-label={`Group ${i + 1} DN`}
                          value={g.dn}
                          onChange={(e) => setGroup(i, { dn: e.target.value })}
                          placeholder="cn=splunk-admins,ou=groups,dc=example,dc=com"
                          maxLength={1024}
                          autoComplete="off"
                          spellCheck={false}
                          className="h-9 w-full rounded-md border border-line-strong bg-surface-2 px-3 font-mono text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus"
                          {...describe(`group_roles.${i}`)}
                        />
                        {err(`group_roles.${i}`)}
                      </Td>
                      <Td>
                        <select aria-label={`Group ${i + 1} role`} value={g.role} onChange={(e) => setGroup(i, { role: e.target.value as Role })} className={SELECT}>
                          <option value="viewer">Viewer</option>
                          <option value="admin">Admin</option>
                        </select>
                      </Td>
                      <Td>
                        <Button type="button" size="sm" variant="outline" aria-label={`Remove group ${i + 1}`} onClick={() => edit({ group_roles: draft.group_roles.filter((_, j) => j !== i) })}>
                          <Trash2 aria-hidden className="h-4 w-4" />
                        </Button>
                      </Td>
                    </Tr>
                  ))}
                </TBody>
              </Table>
            )}
            {err("group_roles")}
            <Button type="button" variant="outline" size="sm" className="justify-self-start" onClick={() => edit({ group_roles: [...draft.group_roles, { dn: "", role: "viewer" }] })}>
              <Plus aria-hidden className="h-4 w-4" /> Add group
            </Button>
          </div>
        </section>

        <section aria-labelledby="mfa-title" className="glass grid gap-2 p-4">
          <h2 id="mfa-title" className="text-base font-semibold">
            MFA for directory users
          </h2>
          <span className="flex items-center gap-2">
            <input id={fid("require_mfa")} type="checkbox" className={BOX} checked={draft.require_mfa} onChange={(e) => edit({ require_mfa: e.target.checked })} aria-describedby={`${fid("require_mfa")}-hint`} />
            <Label htmlFor={fid("require_mfa")}>Require MFA for directory users</Label>
          </span>
          <p id={`${fid("require_mfa")}-hint`} className="text-[13px] text-subtle">
            Directory users can always set up MFA in Parsemaxxing; this makes it required at sign-in. Directory admins need MFA whenever admins do. {source("require_mfa")}.
          </p>
        </section>

        <details className="glass p-4">
          <summary className="cursor-pointer text-base font-semibold">Advanced</summary>
          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            <Field id={fid("connect_timeout_seconds")} label="Connect timeout (seconds)" type="number" min={1} max={60} value={draft.connect_timeout_seconds} onChange={(e) => edit({ connect_timeout_seconds: Number(e.target.value) })} hint={`1 to 60. ${source("connect_timeout_seconds")}.`} error={errors.connect_timeout_seconds} />
            <Field id={fid("read_timeout_seconds")} label="Read timeout (seconds)" type="number" min={1} max={120} value={draft.read_timeout_seconds} onChange={(e) => edit({ read_timeout_seconds: Number(e.target.value) })} hint={`1 to 120. ${source("read_timeout_seconds")}.`} error={errors.read_timeout_seconds} />
            <Field id={fid("page_size")} label="Page size (entries)" type="number" min={1} max={5000} value={draft.page_size} onChange={(e) => edit({ page_size: Number(e.target.value) })} hint={`1 to 5000. ${source("page_size")}.`} error={errors.page_size} />
            <Field id={fid("session_max_hours")} label="Directory session length (hours)" type="number" min={1} max={24} value={draft.session_max_hours} onChange={(e) => edit({ session_max_hours: Number(e.target.value) })} hint={`1 to 24. Directory sessions end after this many hours so group changes take effect. ${source("session_max_hours")}.`} error={errors.session_max_hours} />
          </div>
        </details>

        <div className="glass sticky bottom-0 z-10 flex flex-wrap items-center gap-3 p-3">
          <Button type="submit" disabled={saving}>
            Save
          </Button>
          <Button type="button" variant="outline" disabled={!dirty} onClick={load}>
            Discard changes
          </Button>
          {dirty && <span className="text-sm text-warn">You have unsaved changes.</span>}
          <p role="status" aria-live="polite" className="text-sm text-good empty:hidden">
            {message}
          </p>
          <FormError error={saveError} />
          {conflict && (
            <div role="alert" className="flex flex-wrap items-center gap-2 text-sm text-bad">
              The LDAP settings changed while you were editing. Reload to see them; your unsaved changes here are dropped.
              <Button type="button" size="sm" variant="outline" onClick={load}>
                Reload
              </Button>
            </div>
          )}
        </div>
      </form>

      <Tests dirty={dirty} />
    </>
  );
}

function CaBundle({ certs, version, reload, onUploaded }: { certs: Certificate[] | null; version: number; reload: () => void; onUploaded: (v: LdapView) => void }) {
  const [pem, setPem] = useState("");
  const [error, setError] = useState<string | Error>("");
  const [conflict, setConflict] = useState(false);
  const shown = certs;
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [bind, setBind] = useState("");
  const [current, setCurrent] = useState("");
  const [round, setRound] = useState(0); // remounts the password fields to clear them
  const [fields, setFields] = useState<Errors>({});

  async function upload() {
    setError("");
    setMessage("");
    setConflict(false);
    const f: Errors = {};
    if (!bind) f.bind = "Enter the bind password again: a new CA bundle needs it.";
    if (!current) f.current = "Enter your own password to confirm this change.";
    setFields(f);
    if (!pem.includes("-----BEGIN CERTIFICATE-----")) return setError("Paste or choose a PEM file with one or more CA certificates (-----BEGIN CERTIFICATE-----).");
    if (Object.keys(f).length) return;
    setBusy(true);
    try {
      const v = await postJson<LdapView>("/auth/ldap/ca-bundle", { pem, bind_password: bind, current_password: current, expected_version: version });
      const n = v.ca_bundle?.length ?? 0;
      setPem("");
      setBind("");
      setCurrent("");
      setRound(round + 1);
      setMessage(`CA bundle and bind password stored: ${n} ${n === 1 ? "certificate" : "certificates"}. Directory users were signed out.`);
      onUploaded(v);
    } catch (e) {
      const onField = e instanceof ApiError ? passwordField(e) : null;
      if (onField) setFields({ [onField === "bind_password" ? "bind" : "current"]: (e as Error).message });
      else if (e instanceof ApiError && e.status === 409) setConflict(true);
      else setError(e as Error);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby="ca-title" className="glass grid gap-3 p-4">
      <h2 id="ca-title" className="text-base font-semibold">
        CA bundle
      </h2>
      <p className="text-[13px] text-subtle">Only these certificates are trusted for the directory. Uploading replaces the current bundle and the bind password at once, and signs directory users out.</p>
      {shown && shown.length > 0 ? (
        <Table aria-label="CA certificates">
          <THead>
            <Tr>
              <Th scope="col">Subject</Th>
              <Th scope="col">Issuer</Th>
              <Th scope="col">Expires</Th>
              <Th scope="col">SHA-256</Th>
            </Tr>
          </THead>
          <TBody>
            {shown.map((c) => (
              <Tr key={c.sha256}>
                <Td className="break-all font-mono text-[13px]">{c.subject}</Td>
                <Td className="break-all font-mono text-[13px]">{c.issuer}</Td>
                <Td className="whitespace-nowrap">{when(c.not_after)}</Td>
                <Td className="break-all font-mono text-[13px]">{c.sha256}</Td>
              </Tr>
            ))}
          </TBody>
        </Table>
      ) : (
        <p className="text-sm text-muted">No CA bundle yet. Start here: upload the CA that signed your directory servers&apos; certificates, with the bind password. Then add the servers and save.</p>
      )}
      <div className="grid gap-1">
        <Label htmlFor="ldap-ca-pem">{shown?.length ? "Replace with a new bundle (PEM)" : "CA bundle (PEM)"}</Label>
        <textarea
          id="ldap-ca-pem"
          value={pem}
          onChange={(e) => setPem(e.target.value)}
          rows={5}
          spellCheck={false}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? "ldap-ca-pem-hint ldap-ca-pem-error" : "ldap-ca-pem-hint"}
          className="rounded-md border border-line-strong bg-surface-2 p-2 font-mono text-[13px] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus"
        />
        <p id="ldap-ca-pem-hint" className="text-[13px] text-subtle">
          Paste the certificates, or choose a file. CA certificates only, unexpired, at most 256 KB.
        </p>
        {error && (
          <p id="ldap-ca-pem-error" role="alert" className="text-sm text-bad">
            {typeof error === "string" ? error : error.message}
          </p>
        )}
      </div>
      <div key={round} className="grid gap-3 sm:grid-cols-2">
        <div onChange={(e) => setBind((e.target as HTMLInputElement).value)}>
          <PasswordField id="ldap-ca-bind-password" label="Bind password for this upload (required)" autoComplete="new-password" hint="A new CA bundle needs the bind password again." error={fields.bind} />
        </div>
        <div onChange={(e) => setCurrent((e.target as HTMLInputElement).value)}>
          <PasswordField id="ldap-ca-current-password" label="Your password for this upload (required)" autoComplete="current-password" hint="Confirms it is you changing which certificates are trusted." error={fields.current} />
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <Label htmlFor="ldap-ca-file" className="sr-only">
          CA bundle file
        </Label>
        <input
          id="ldap-ca-file"
          type="file"
          accept=".pem,.crt,.cer,text/plain"
          className="text-sm file:mr-2 file:rounded-full file:border file:border-line-strong file:bg-surface-2 file:px-3 file:py-1 file:text-fg"
          onChange={async (e) => {
            const f = e.target.files?.[0];
            if (f) setPem(f.size > 256 * 1024 ? "" : await f.text());
            if (f && f.size > 256 * 1024) setError("That file is over 256 KB. Upload only the CA certificates.");
          }}
        />
        <Button type="button" variant="outline" disabled={busy || !pem} onClick={upload}>
          <Upload aria-hidden className="h-4 w-4" /> Upload CA bundle
        </Button>
        <p role="status" aria-live="polite" className="text-sm text-good empty:hidden">
          {message}
        </p>
      </div>
      {conflict && (
        <div role="alert" className="flex flex-wrap items-center gap-2 text-sm text-bad">
          The LDAP settings changed while you were editing. Reload, then upload again.
          <Button type="button" size="sm" variant="outline" onClick={reload}>
            Reload
          </Button>
        </div>
      )}
    </section>
  );
}

function Result({ ok, yes = "Passed", no = "Failed" }: { ok: boolean; yes?: string; no?: string }) {
  return ok ? (
    <Badge variant="good">
      <CircleCheck aria-hidden className="h-3.5 w-3.5" /> {yes}
    </Badge>
  ) : (
    <Badge variant="bad">
      <CircleX aria-hidden className="h-3.5 w-3.5" /> {no}
    </Badge>
  );
}

function Tests({ dirty }: { dirty: boolean }) {
  const [conn, setConn] = useState<LdapConnection | null>(null);
  const [connError, setConnError] = useState<string | Error>("");
  const [testing, setTesting] = useState(false);
  const [username, setUsername] = useState("");
  const [lookup, setLookup] = useState<LdapLookup | null>(null);
  const [lookupError, setLookupError] = useState<string | Error>("");
  const [looking, setLooking] = useState(false);

  async function testConnection() {
    setTesting(true);
    setConn(null);
    setConnError("");
    try {
      setConn(await postJson<LdapConnection>("/auth/ldap/test-connection", {}));
    } catch (e) {
      setConnError(e as Error);
    } finally {
      setTesting(false);
    }
  }

  async function testLookup(e: React.FormEvent) {
    e.preventDefault();
    setLookup(null);
    setLookupError("");
    if (!username.trim()) return setLookupError("Enter a user name to look up.");
    setLooking(true);
    try {
      setLookup(await postJson<LdapLookup>("/auth/ldap/test-user-lookup", { username: username.trim() }));
    } catch (err) {
      setLookupError(err as Error);
    } finally {
      setLooking(false);
    }
  }

  return (
    <section aria-labelledby="tests-title" className="glass grid gap-4 p-4">
      <h2 id="tests-title" className="text-base font-semibold">
        Tests
      </h2>
      <p className="text-[13px] text-subtle">Tests use the saved settings.{dirty && " Save first to test your changes."}</p>

      <div className="grid gap-2">
        <Button type="button" variant="outline" className="justify-self-start" disabled={testing} onClick={testConnection}>
          {testing ? "Testing…" : "Test connection"}
        </Button>
        <FormError error={connError} />
        <div aria-live="polite" className="grid gap-3">
          {conn &&
            conn.servers.map((s, i) => (
              <div key={i} className="rounded-md border border-line p-3" aria-label={`Server ${i + 1} test`} role="group">
                <p className="flex flex-wrap items-center gap-2 text-sm">
                  <span className="font-mono">{s.url}</span> <Result ok={s.ok} />
                </p>
                <ol className="mt-2 grid gap-1 text-sm">
                  {s.steps.map((st, j) => (
                    <li key={j} className="grid gap-1">
                      <span className="flex flex-wrap items-center gap-2">
                        <span className="w-32 font-medium">{STEPS[st.step] ?? st.step}</span>
                        <Result ok={st.ok} />
                        <span className="text-muted">{st.detail}</span>
                      </span>
                      {st.certificate_info && (
                        <dl className="ml-32 grid grid-cols-[auto_1fr] gap-x-3 text-[13px]">
                          <dt className="text-muted">Subject</dt>
                          <dd className="break-all font-mono">{st.certificate_info.subject}</dd>
                          <dt className="text-muted">Issuer</dt>
                          <dd className="break-all font-mono">{st.certificate_info.issuer}</dd>
                          <dt className="text-muted">Expires</dt>
                          <dd>{when(st.certificate_info.not_after)}</dd>
                          <dt className="text-muted">SHA-256</dt>
                          <dd className="break-all font-mono">{st.certificate_info.sha256}</dd>
                        </dl>
                      )}
                    </li>
                  ))}
                </ol>
              </div>
            ))}
        </div>
      </div>

      <form onSubmit={testLookup} noValidate className="grid gap-2 border-t border-line pt-4">
        <div className="flex flex-wrap items-end gap-3">
          <div className="sm:w-72">
            <Field id="ldap-lookup" label="User name to look up" value={username} onChange={(e) => setUsername(e.target.value)} maxLength={256} autoComplete="off" autoCapitalize="none" spellCheck={false} hint="Shows the DN, matched groups and role. Never other attributes or a password." />
          </div>
          <Button type="submit" variant="outline" disabled={looking}>
            {looking ? "Looking up…" : "Test a user lookup"}
          </Button>
        </div>
        <FormError error={lookupError} />
        <div aria-live="polite">
          {lookup && (
            <div role="group" aria-label="Lookup result" className="grid gap-2 rounded-md border border-line p-3 text-sm">
              <p className="flex flex-wrap items-center gap-2">
                <Result ok={lookup.ok} yes="Can sign in" no="Can't sign in" />
                <span>{lookup.message}</span>
              </p>
              <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
                <dt className="text-muted">Entries found</dt>
                <dd>{lookup.found}</dd>
                <dt className="text-muted">DN</dt>
                <dd className="break-all font-mono">{lookup.dn ?? "None"}</dd>
                <dt className="text-muted">Matched groups</dt>
                <dd>
                  {lookup.matched_groups.length ? (
                    <ul>
                      {lookup.matched_groups.map((g) => (
                        <li key={g} className="break-all font-mono">
                          {g}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    "None"
                  )}
                </dd>
                <dt className="text-muted">Role</dt>
                <dd>{roleWord(lookup.role)}</dd>
              </dl>
            </div>
          )}
        </div>
      </form>
    </section>
  );
}
