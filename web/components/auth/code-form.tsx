"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { CODE_RULE, CodeField, Field, formValues, mfaCode } from "@/components/auth/fields";
import { notice } from "@/components/auth/session";
import { Button } from "@/components/ui/button";
import { postJson, type SignedIn } from "@/lib/api";
import { safeNext } from "@/lib/next-path";

/** The way out of a partial session (MFA step, recovery code, forced enrolment). */
export function SignInAsSomeoneElse() {
  const router = useRouter();
  return (
    <button
      type="button"
      className="justify-self-start text-sm underline underline-offset-2"
      onClick={() => postJson("/auth/logout", {}).finally(() => router.replace("/login"))}
    >
      Sign in as someone else
    </button>
  );
}

/** The second sign-in step: a 6-digit code, or one recovery code. */
export function CodeForm({ recovery }: { recovery: boolean }) {
  const router = useRouter();
  const params = useSearchParams();
  const next = params.get("next");
  const [error, setError] = useState<string | Error>("");
  const [busy, setBusy] = useState(false);
  const back = `?next=${encodeURIComponent(safeNext(next))}`;

  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const raw = formValues(e)("code");
    const code = recovery ? raw.trim() : mfaCode(raw);
    if (!code) return setError(recovery ? "Enter a recovery code." : CODE_RULE);
    setBusy(true);
    setError("");
    try {
      const r = await postJson<SignedIn>("/auth/login/mfa", recovery ? { recovery_code: code } : { code });
      if (r.recovery_codes_left !== undefined) notice.recoveryLeft = r.recovery_codes_left;
      router.replace(safeNext(next));
    } catch (err) {
      setError(err as Error);
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby="mfa-title" className="glass grid gap-4 p-6">
      <h1 id="mfa-title" className="text-xl font-semibold">
        {recovery ? "Use a recovery code" : "Enter your MFA code"}
      </h1>
      <form onSubmit={submit} className="grid gap-4">
        {recovery ? (
          <Field id="code" label="Recovery code" hint="Each recovery code works once." error={error} autoComplete="off" aria-required maxLength={64} spellCheck={false} />
        ) : (
          <CodeField hint="From your authenticator app." error={error} />
        )}
        <Button type="submit" disabled={busy}>
          {busy ? "Verifying…" : "Verify"}
        </Button>
      </form>
      <Link href={`${recovery ? "/login/mfa" : "/login/recovery"}${back}`} className="text-sm underline underline-offset-2">
        {recovery ? "Use a 6-digit code instead" : "Use a recovery code instead"}
      </Link>
      {recovery && <p className="text-sm text-muted">Lost your authenticator and your codes? Ask an admin to reset your MFA.</p>}
      <SignInAsSomeoneElse />
    </section>
  );
}
