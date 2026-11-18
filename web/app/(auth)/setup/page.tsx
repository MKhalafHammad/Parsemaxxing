"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Field, FormError, formValues, PasswordField } from "@/components/auth/fields";
import { Button } from "@/components/ui/button";
import { api, postJson, type SignedIn } from "@/lib/api";
import { stagePath } from "@/lib/next-path";

export default function SetupPage() {
  const router = useRouter();
  const [needed, setNeeded] = useState<boolean | null>(null);
  const [error, setError] = useState<string | Error>("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api<{ needed: boolean }>("/setup").then((s) => setNeeded(s.needed), setError);
  }, []);

  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const v = formValues(e);
    if (v("password") !== v("password2")) {
      setError("The two passwords don't match. Type the same password twice.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const r = await postJson<SignedIn>("/setup", { token: v("token").trim(), username: v("username"), display_name: v("display_name"), password: v("password") });
      router.replace(stagePath(r.stage, "/"));
    } catch (err) {
      setError(err as Error);
      setBusy(false);
    }
  }

  if (needed === false) {
    return (
      <section aria-labelledby="setup-title" className="glass grid gap-3 p-6">
        <h1 id="setup-title" className="text-xl font-semibold">
          Setup is already complete
        </h1>
        <Link href="/login" className="underline underline-offset-2">
          Sign in
        </Link>
      </section>
    );
  }
  return (
    <section aria-labelledby="setup-title" className="glass grid gap-4 p-6">
      <h1 id="setup-title" className="text-xl font-semibold">
        Create the first admin
      </h1>
      <p className="text-sm text-muted">Parsemaxxing has no admin yet. Enter the setup token from the engine&apos;s data volume. It is valid for 60 minutes and works once. To read it:</p>
      <pre className="overflow-x-auto rounded-md bg-surface-2 p-2 font-mono text-[13px]">docker compose exec engine cat /app/.runs/setup-token</pre>
      {needed === null && !error ? (
        <p aria-busy="true" className="text-sm text-muted">
          Loading…
        </p>
      ) : (
        <form onSubmit={submit} className="grid gap-4">
          <Field id="token" label="Setup token" autoComplete="off" required maxLength={128} spellCheck={false} />
          <Field id="username" label="User name" autoComplete="username" required maxLength={64} autoCapitalize="none" spellCheck={false} hint="1 to 64 of a-z, 0-9, '.', '_' and '-'." />
          <Field id="display_name" label="Display name (optional)" autoComplete="name" maxLength={128} />
          <PasswordField id="password" label="Password" autoComplete="new-password" hint="12 to 128 characters. Common passwords are refused." />
          <PasswordField id="password2" label="Password again" autoComplete="new-password" />
          <FormError error={error} />
          <Button type="submit" disabled={busy}>
            {busy ? "Creating…" : "Continue"}
          </Button>
        </form>
      )}
    </section>
  );
}
