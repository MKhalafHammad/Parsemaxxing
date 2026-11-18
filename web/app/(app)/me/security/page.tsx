"use client";

import { CircleCheck, Circle } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { FormError, formValues, PasswordField } from "@/components/auth/fields";
import { RecoveryCodes } from "@/components/auth/recovery-codes";
import { useSession } from "@/components/auth/session";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Confirm } from "@/components/ui/confirm";
import { Table, TBody, Td, Th, THead, Tr } from "@/components/ui/table";
import { api, postJson, type Session } from "@/lib/api";
import { when } from "@/lib/utils";

export default function SecurityPage() {
  const { me } = useSession();
  const router = useRouter();
  const [sessions, setSessions] = useState<Session[]>([]);
  const [loadError, setLoadError] = useState<string | Error>("");
  const [mfaOn, setMfaOn] = useState(!!me?.user.mfa);
  const [codes, setCodes] = useState<string[] | null>(null);
  const [pwError, setPwError] = useState<string | Error>("");
  const [codesError, setCodesError] = useState<string | Error>("");
  const [message, setMessage] = useState("");
  const [dialog, setDialog] = useState<"disable" | "everywhere" | Session | null>(null);

  const load = useCallback(() => {
    api<Session[]>("/auth/sessions").then(setSessions, setLoadError);
  }, []);
  useEffect(load, [load]);

  async function changePassword(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const v = formValues(e);
    setPwError("");
    if (v("new_password") !== v("new_password2")) return setPwError("The two new passwords don't match. Type the same password twice.");
    try {
      await postJson("/auth/password", { current_password: v("current_password"), new_password: v("new_password") });
      form.reset();
      setMessage("Password changed. Your other sessions were signed out.");
      load();
    } catch (err) {
      setPwError(err as Error);
    }
  }

  async function newCodes(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    setCodesError("");
    try {
      const r = await postJson<{ recovery_codes: string[] }>("/auth/mfa/recovery-codes", { password: formValues(e)("codes_password") });
      form.reset();
      setCodes(r.recovery_codes);
    } catch (err) {
      setCodesError(err as Error);
    }
  }

  if (!me) return null;
  return (
    <div className="grid max-w-3xl gap-6">
      <div>
        <h1 className="text-xl font-semibold">Account security</h1>
        <p className="text-sm text-muted">
          Signed in as <span className="font-mono">{me.user.username}</span> ({me.user.role === "admin" ? "Admin" : "Viewer"}, {me.user.source === "local" ? "local account" : me.user.source}).
        </p>
      </div>
      <p role="status" aria-live="polite" className="text-sm text-good empty:hidden">
        {message}
      </p>

      {me.user.source === "local" && (
        <section aria-labelledby="pw-title" className="glass grid gap-3 p-4">
          <h2 id="pw-title" className="text-base font-semibold">
            Change password
          </h2>
          <form onSubmit={changePassword} className="grid gap-3 sm:max-w-sm">
            <PasswordField id="current_password" label="Current password" autoComplete="current-password" />
            <PasswordField id="new_password" label="New password" autoComplete="new-password" hint="12 to 128 characters. Common passwords are refused." />
            <PasswordField id="new_password2" label="New password again" autoComplete="new-password" />
            <FormError error={pwError} />
            <Button type="submit" className="justify-self-start">
              Change password
            </Button>
          </form>
        </section>
      )}

      <section id="mfa" aria-labelledby="mfa-title" className="glass grid gap-3 p-4">
        <h2 id="mfa-title" className="flex items-center gap-2 text-base font-semibold">
          MFA
          {mfaOn ? (
            <Badge variant="good">
              <CircleCheck aria-hidden className="h-3.5 w-3.5" /> On
            </Badge>
          ) : (
            <Badge>
              <Circle aria-hidden className="h-3.5 w-3.5" /> Off
            </Badge>
          )}
        </h2>
        {!mfaOn ? (
          <Button asChild variant="outline" className="justify-self-start">
            <Link href="/mfa/enrol?next=%2Fme%2Fsecurity">Set up MFA</Link>
          </Button>
        ) : codes ? (
          <RecoveryCodes codes={codes} onDone={() => setCodes(null)} />
        ) : (
          <>
            <form id="recovery" onSubmit={newCodes} className="grid gap-3 sm:max-w-sm" aria-describedby="recovery-help">
              <h3 className="text-sm font-semibold">Recovery codes</h3>
              <p id="recovery-help" className="text-sm text-muted">
                Creating new codes makes the old ones stop working.
              </p>
              <PasswordField id="codes_password" label="Password" autoComplete="current-password" />
              <FormError error={codesError} />
              <Button type="submit" variant="outline" className="justify-self-start">
                Create new codes
              </Button>
            </form>
            <Button variant="destructive" className="justify-self-start" onClick={() => setDialog("disable")}>
              Turn off MFA…
            </Button>
          </>
        )}
      </section>

      <section aria-labelledby="sessions-title" className="glass grid gap-3 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 id="sessions-title" className="text-base font-semibold">
            Active sessions
          </h2>
          <Button variant="outline" size="sm" onClick={() => setDialog("everywhere")}>
            Sign out everywhere
          </Button>
        </div>
        <FormError error={loadError} />
        <Table aria-label="Active sessions">
          <THead>
            <Tr>
              <Th scope="col">Device</Th>
              <Th scope="col">IP</Th>
              <Th scope="col">Signed in</Th>
              <Th scope="col">Last seen</Th>
              <Th scope="col">
                <span className="sr-only">Actions</span>
              </Th>
            </Tr>
          </THead>
          <TBody>
            {sessions.map((s) => (
              <Tr key={s.id}>
                <Td className="break-all">
                  {s.user_agent || "Unknown device"} {s.current && <Badge variant="running">This session</Badge>}
                </Td>
                <Td className="font-mono text-[13px]">{s.ip}</Td>
                <Td className="whitespace-nowrap">{when(s.created_at)}</Td>
                <Td className="whitespace-nowrap">{when(s.last_seen_at)}</Td>
                <Td>
                  <Button size="sm" variant="outline" onClick={() => setDialog(s)}>
                    Revoke…
                  </Button>
                </Td>
              </Tr>
            ))}
          </TBody>
        </Table>
      </section>

      <Confirm
        open={dialog === "disable"}
        onClose={() => setDialog(null)}
        title="Turn off MFA?"
        confirm="Turn off MFA"
        destructive
        onConfirm={async (f) => {
          await postJson("/auth/mfa/disable", { password: f.get("disable_password") });
          setMfaOn(false);
          setMessage("MFA is off. Your other sessions were signed out.");
          load();
        }}
      >
        <p className="text-sm">Signing in will need only your password. Your recovery codes stop working.</p>
        <PasswordField id="disable_password" label="Password" autoComplete="current-password" />
      </Confirm>
      <Confirm
        open={dialog === "everywhere"}
        onClose={() => setDialog(null)}
        title="Sign out everywhere?"
        confirm="Sign out everywhere"
        destructive
        onConfirm={async () => {
          await postJson("/auth/sessions/revoke-all", {});
          router.replace("/login");
        }}
      >
        <p className="text-sm">Ends every session of yours, including this one.</p>
      </Confirm>
      <Confirm
        open={typeof dialog === "object" && dialog !== null}
        onClose={() => setDialog(null)}
        title="Revoke this session?"
        confirm="Revoke session"
        destructive
        onConfirm={async () => {
          const s = dialog as Session;
          await postJson(`/auth/sessions/${s.id}/revoke`, {});
          if (s.current) router.replace("/login");
          else load();
        }}
      >
        <p className="text-sm">{(dialog as Session | null)?.current ? "This is the session you are using: you will be signed out." : "That device is signed out at once."}</p>
      </Confirm>
    </div>
  );
}
