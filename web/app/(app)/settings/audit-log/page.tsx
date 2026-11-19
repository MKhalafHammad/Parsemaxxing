"use client";

import { CircleCheck, CircleX, Circle } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { FormError } from "@/components/auth/fields";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/input";
import { Table, TBody, Td, Th, THead, Tr } from "@/components/ui/table";
import { api, type AuditEvent } from "@/lib/api";
import { when } from "@/lib/utils";

const PAGE = 25;
// The engine's auth event names (auth/service.py, auth/events.py), with their words.
const EVENTS: Record<string, string> = {
  login: "Sign-in",
  logout: "Sign-out",
  lockout: "Lockout",
  mfa_verify: "MFA check",
  mfa_enrol: "MFA enrol started",
  mfa_confirm: "MFA turned on",
  mfa_disable: "MFA turned off",
  recovery_codes: "Recovery codes created",
  reauth: "Password re-check",
  password_change: "Password change",
  session_revoke: "Session revoked",
  token_create: "Token created",
  token_revoke: "Token revoked",
  token_use: "Token use",
  user_create: "User added",
  role_change: "Role change",
  user_disable: "User disabled",
  user_enable: "User enabled",
  setup: "First-run setup",
  setup_token_issued: "Setup token issued",
  admin_reset: "Break-glass reset",
  ldap_settings_change: "LDAP settings changed",
  ldap_ca_bundle: "LDAP CA bundle uploaded",
  ldap_test: "LDAP test",
};

function Outcome({ outcome }: { outcome: string }) {
  if (outcome === "success")
    return (
      <Badge variant="good">
        <CircleCheck aria-hidden className="h-3.5 w-3.5" /> Success
      </Badge>
    );
  if (outcome === "failure" || outcome === "refused")
    return (
      <Badge variant="bad">
        <CircleX aria-hidden className="h-3.5 w-3.5" /> {outcome === "failure" ? "Failure" : "Refused"}
      </Badge>
    );
  return (
    <Badge>
      <Circle aria-hidden className="h-3.5 w-3.5" /> {outcome}
    </Badge>
  );
}

function AuditLog() {
  const router = useRouter();
  const params = useSearchParams();
  const event = params.get("event") ?? "";
  const before = params.get("before") ?? "";
  const key = `${event}|${before}`;
  const [loaded, setLoaded] = useState<{ key: string; rows: AuditEvent[] } | null>(null);
  const rows = loaded?.key === key ? loaded.rows : null;
  const [error, setError] = useState<string | Error>("");

  useEffect(() => {
    const q = new URLSearchParams({ limit: String(PAGE + 1) });
    if (EVENTS[event]) q.set("event", event);
    if (/^\d+$/.test(before)) q.set("before", before);
    api<AuditEvent[]>(`/audit?${q}`).then((r) => setLoaded({ key: `${event}|${before}`, rows: r }), setError);
  }, [event, before]);

  const go = (p: Record<string, string>) => {
    const q = new URLSearchParams({ ...(event ? { event } : {}), ...p });
    for (const [k, v] of [...q]) if (!v) q.delete(k);
    router.push(`/settings/audit-log${q.size ? `?${q}` : ""}`);
  };
  const page = (rows ?? []).slice(0, PAGE);
  const older = (rows?.length ?? 0) > PAGE;

  return (
    <div className="grid gap-6">
      <div>
        <h1 className="text-xl font-semibold">Audit log</h1>
        <p className="text-sm text-muted">Sign-ins, account and token changes, newest first. Nobody can edit the audit log.</p>
      </div>
      <FormError error={error} />
      <section aria-labelledby="audit-title" aria-busy={rows === null} className="glass overflow-hidden">
        <div className="flex flex-wrap items-center gap-3 border-b border-line px-4 py-3">
          <h2 id="audit-title" className="text-base font-semibold">
            Events
          </h2>
          <Label htmlFor="event-filter" className="ml-auto text-muted">
            Action
          </Label>
          <select id="event-filter" value={event} onChange={(e) => go({ event: e.target.value, before: "" })} className="h-8 rounded-md border border-line-strong bg-surface-solid px-2 text-sm">
            <option value="">All actions</option>
            {Object.entries(EVENTS).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </div>
        {rows === null ? (
          <p className="p-4 text-sm text-muted">Loading…</p>
        ) : page.length === 0 ? (
          <p className="p-4 text-sm text-muted">
            {event || before ? (
              <>
                No events match these filters.{" "}
                <Link href="/settings/audit-log" className="underline underline-offset-2">
                  Clear filters
                </Link>
              </>
            ) : (
              "No events yet. Sign-ins and account changes appear here."
            )}
          </p>
        ) : (
          <Table aria-label="Audit log">
            <THead>
              <Tr>
                <Th scope="col" className="pl-4">Time</Th>
                <Th scope="col">Actor</Th>
                <Th scope="col">Action</Th>
                <Th scope="col">Outcome</Th>
                <Th scope="col">Client IP</Th>
                <Th scope="col">Detail</Th>
              </Tr>
            </THead>
            <TBody>
              {page.map((r) => (
                <Tr key={r.id}>
                  <Td className="whitespace-nowrap pl-4">{when(r.at, { absolute: true })}</Td>
                  <Td className="break-all">{r.actor}</Td>
                  <Td>{EVENTS[r.event] ?? r.event}</Td>
                  <Td>
                    <Outcome outcome={r.outcome} />
                  </Td>
                  <Td className="font-mono text-[13px]">{r.ip}</Td>
                  <Td className="break-all font-mono text-[12px] text-muted">{Object.keys(r.detail ?? {}).length ? JSON.stringify(r.detail) : ""}</Td>
                </Tr>
              ))}
            </TBody>
          </Table>
        )}
        <nav aria-label="Pages" className="flex justify-end gap-2 px-4 py-3">
          {before && (
            <Button size="sm" variant="outline" onClick={() => go({ before: "" })}>
              Newest
            </Button>
          )}
          {older && (
            <Button size="sm" variant="outline" onClick={() => go({ before: String(page[page.length - 1]!.id) })}>
              Older
            </Button>
          )}
        </nav>
      </section>
    </div>
  );
}

export default function AuditPage() {
  return (
    <Suspense>
      <AuditLog />
    </Suspense>
  );
}
