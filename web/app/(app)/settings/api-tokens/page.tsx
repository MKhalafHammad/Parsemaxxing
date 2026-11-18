"use client";

import { Circle, CircleAlert, CircleCheck, CircleX, Copy, Plus, TriangleAlert } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { Field, FormError, formValues } from "@/components/auth/fields";
import { useSession } from "@/components/auth/session";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Confirm } from "@/components/ui/confirm";
import { Dialog } from "@/components/ui/dialog";
import { Label } from "@/components/ui/input";
import { Table, TBody, Td, Th, THead, Tr } from "@/components/ui/table";
import { api, postJson, type ApiToken } from "@/lib/api";
import { when } from "@/lib/utils";

type Created = { token: string; name: string; expires_at: string };
const STATUS = {
  active: { word: "Active", variant: "good", Icon: CircleCheck },
  expired: { word: "Expired", variant: "default", Icon: Circle },
  revoked: { word: "Revoked", variant: "bad", Icon: CircleX },
} as const;
const DAY = 86_400_000;

export default function TokensPage() {
  const { me, isAdmin } = useSession();
  const [tokens, setTokens] = useState<ApiToken[] | null>(null);
  const [filter, setFilter] = useState("");
  const [error, setError] = useState<string | Error>("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | Error>("");
  const [days, setDays] = useState(30);
  const [now, setNow] = useState(() => Date.now());
  const [created, setCreated] = useState<Created | null>(null);
  const [copied, setCopied] = useState(false);
  const [copyFailed, setCopyFailed] = useState(false);
  const [nameError, setNameError] = useState("");
  const [leaving, setLeaving] = useState(false);
  const [revoking, setRevoking] = useState<ApiToken | null>(null);

  const load = useCallback(() => {
    api<ApiToken[]>("/auth/tokens").then(setTokens, setError);
  }, []);
  useEffect(load, [load]);

  async function create(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const v = formValues(e);
    setCreateError("");
    const name = v("name").trim();
    setNameError(/^[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}$/.test(name) ? "" : "Enter a name of 1 to 64 letters, digits, spaces, '.', '_' and '-'.");
    if (!/^[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}$/.test(name) || !(days >= 1 && days <= 90)) return;
    try {
      const r = await postJson<Created>("/auth/tokens", { name, role: v("role"), expires_in_days: Number(v("days")) });
      setCreating(false);
      setCopied(false);
      setCopyFailed(false);
      setLeaving(false);
      setCreated(r);
      load();
    } catch (err) {
      setCreateError(err as Error);
    }
  }

  const closeCreated = () => {
    if (!copied && !leaving) return setLeaving(true);
    setCreated(null); // the value leaves the page with the dialog
  };

  const shown = (tokens ?? []).filter((t) => !filter || t.status === filter);
  return (
    <div className="grid gap-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">API tokens</h1>
          <p className="text-sm text-muted">
            {isAdmin ? "Every token on the platform. Admins can revoke any of them." : "Your tokens. A token's role is never higher than yours."}
          </p>
        </div>
        <Button
          onClick={() => {
            setDays(30);
            setNow(Date.now());
            setCreateError("");
            setCreating(true);
          }}
        >
          <Plus aria-hidden className="h-4 w-4" /> Create token
        </Button>
      </div>
      <FormError error={error} />

      <section aria-labelledby="tokens-title" className="glass overflow-hidden">
        <div className="flex flex-wrap items-center gap-3 border-b border-line px-4 py-3">
          <h2 id="tokens-title" className="text-base font-semibold">
            Tokens
          </h2>
          <Label htmlFor="status-filter" className="ml-auto text-muted">
            Status
          </Label>
          <select id="status-filter" value={filter} onChange={(e) => setFilter(e.target.value)} className="h-8 rounded-md border border-line-strong bg-surface-solid px-2 text-sm">
            <option value="">All</option>
            <option value="active">Active</option>
            <option value="expired">Expired</option>
            <option value="revoked">Revoked</option>
          </select>
        </div>
        {tokens === null ? (
          <p aria-busy="true" className="p-4 text-sm text-muted">
            Loading…
          </p>
        ) : tokens.length === 0 ? (
          <p className="p-4 text-sm text-muted">No API tokens yet. Create one for a script or CI job with “Create token”.</p>
        ) : shown.length === 0 ? (
          <p className="p-4 text-sm text-muted">
            No tokens match this filter.{" "}
            <button type="button" className="underline underline-offset-2" onClick={() => setFilter("")}>
              Clear filters
            </button>
          </p>
        ) : (
          <Table aria-label="API tokens">
            <THead>
              <Tr>
                <Th scope="col" className="pl-4">Name</Th>
                <Th scope="col">Owner</Th>
                <Th scope="col">Role</Th>
                <Th scope="col">Created</Th>
                <Th scope="col">Expires</Th>
                <Th scope="col">Last used</Th>
                <Th scope="col">Status</Th>
                <Th scope="col">
                  <span className="sr-only">Actions</span>
                </Th>
              </Tr>
            </THead>
            <TBody>
              {shown.map((t) => {
                const s = STATUS[t.status] ?? STATUS.expired;
                const left = Math.ceil((new Date(t.expires_at.replace(" ", "T")).getTime() - now) / DAY);
                return (
                  <Tr key={t.id}>
                    <Td className="pl-4 font-mono">{t.name}</Td>
                    <Td>{t.owner}</Td>
                    <Td>{t.role === "admin" ? "Admin" : "Viewer"}</Td>
                    <Td className="whitespace-nowrap">{when(t.created_at)}</Td>
                    <Td className="whitespace-nowrap">
                      {when(t.expires_at)}
                      {t.status === "active" && Number.isFinite(left) && (
                        <span className={left <= 3 ? "flex items-center gap-1 font-medium text-bad" : left <= 14 ? "flex items-center gap-1 text-warn" : "block text-muted"}>
                          {left <= 3 ? <CircleAlert aria-hidden className="h-3.5 w-3.5" /> : left <= 14 && <TriangleAlert aria-hidden className="h-3.5 w-3.5" />}
                          {left} {left === 1 ? "day" : "days"} left
                        </span>
                      )}
                    </Td>
                    <Td className="whitespace-nowrap">{when(t.last_used_at)}</Td>
                    <Td>
                      <Badge variant={s.variant}>
                        <s.Icon aria-hidden className="h-3.5 w-3.5" /> {s.word}
                      </Badge>
                    </Td>
                    <Td>
                      {t.status === "active" && (
                        <Button size="sm" variant="outline" onClick={() => setRevoking(t)}>
                          Revoke… <span className="sr-only">{t.name}</span>
                        </Button>
                      )}
                    </Td>
                  </Tr>
                );
              })}
            </TBody>
          </Table>
        )}
      </section>

      <Dialog open={creating} onClose={() => setCreating(false)} title="Create token">
        <form onSubmit={create} className="grid gap-4" noValidate>
          <Field id="name" label="Name" hint="For example ci-runner. Letters, digits, spaces, '.', '_' and '-'." error={nameError || undefined} aria-required maxLength={64} autoComplete="off" data-autofocus />
          <div className="grid gap-1">
            <Label htmlFor="role">Role</Label>
            <select id="role" name="role" defaultValue="viewer" className="h-9 rounded-md border border-line-strong bg-surface-solid px-2 text-sm" aria-describedby="role-hint">
              <option value="viewer">Viewer</option>
              {me?.user.role === "admin" && <option value="admin">Admin</option>}
            </select>
            <p id="role-hint" className="text-[13px] text-subtle">
              No higher than your own role.
            </p>
          </div>
          <Field
            id="days"
            label="Expires in (days)"
            type="number"
            min={1}
            max={90}
            aria-required
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            hint={days >= 1 && days <= 90 ? `1 to 90 days. Expires on ${new Date(now + days * DAY).toLocaleDateString()}.` : undefined}
            error={days >= 1 && days <= 90 ? undefined : "Use 1 to 90 days."}
          />
          <FormError error={createError} />
          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={() => setCreating(false)}>
              Cancel
            </Button>
            <Button type="submit">Create token</Button>
          </div>
        </form>
      </Dialog>

      <Dialog open={created !== null} onClose={closeCreated} title={`Token "${created?.name ?? ""}" created`}>
        {created && (
          <div className="grid gap-3">
            <p className="text-sm">You won&apos;t see this token again. Store it in your secret manager.</p>
            <p aria-label="New token" className="break-all rounded-md bg-surface-2 p-2 font-mono text-sm">
              {created.token}
            </p>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="justify-self-start"
              onClick={() => navigator.clipboard.writeText(created.token).then(() => setCopied(true), () => setCopyFailed(true))}
            >
              <Copy aria-hidden className="h-4 w-4" /> {copied ? "Copied" : "Copy"}
            </Button>
            {copyFailed && !copied && (
              <p role="status" className="text-sm text-warn">
                Copy failed. Select the token and copy it.
              </p>
            )}
            <p className="text-[13px] text-muted">
              Use it from a shell: <code className="font-mono">export PMX_TOKEN=&lt;your token&gt;</code>
            </p>
            {leaving && !copied && (
              <p role="alert" className="text-sm text-warn">
                Close without copying? The token can&apos;t be shown again.
              </p>
            )}
            <div className="flex justify-end gap-2">
              <Button type="button" onClick={closeCreated} data-autofocus>
                {leaving && !copied ? "Close without copying" : "Done"}
              </Button>
            </div>
          </div>
        )}
      </Dialog>

      <Confirm
        open={revoking !== null}
        onClose={() => setRevoking(null)}
        title={`Revoke token "${revoking?.name ?? ""}"?`}
        confirm="Revoke token"
        destructive
        onConfirm={async () => {
          await postJson(`/auth/tokens/${revoking!.id}/revoke`, {});
          load();
        }}
      >
        <p className="text-sm">Anything using it stops working at once.</p>
      </Confirm>
    </div>
  );
}
