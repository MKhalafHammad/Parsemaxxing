"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Field, FormError, formValues, PasswordField } from "@/components/auth/fields";
import { Button } from "@/components/ui/button";
import { CopyButton } from "@/components/ui/copy-button";
import { api, ApiError, postJson, type SignedIn } from "@/lib/api";

const TOKEN_COMMAND = "docker compose exec engine cat /app/.runs/setup-token";

// Which field an engine refusal belongs to: 403 the token, 422 the password (or the user name).
function fieldOf(err: unknown): string {
  if (!(err instanceof ApiError)) return "";
  if (err.status === 403) return "token";
  if (err.status === 422) return /^user name/i.test(err.message) ? "username" : "password";
  return "";
}
import { stagePath } from "@/lib/next-path";

export default function SetupPage() {
  const router = useRouter();
  const [needed, setNeeded] = useState<boolean | null>(null);
  const [error, setError] = useState<string | Error>("");
  const [field, setField] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api<{ needed: boolean }>("/setup").then((s) => setNeeded(s.needed), setError);
  }, []);

  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const v = formValues(e);
    if (v("password") !== v("password2")) {
      setField("password2");
      setError("The two passwords don't match. Type the same password twice.");
      return;
    }
    setBusy(true);
    setError("");
    setField("");
    try {
      const r = await postJson<SignedIn>("/setup", { token: v("token").trim(), username: v("username"), display_name: v("display_name"), password: v("password") });
      router.replace(stagePath(r.stage, "/"));
    } catch (err) {
      setField(fieldOf(err));
      setError(err as Error);
      setBusy(false);
    }
  }

  const on = (name: string) => (field === name && error ? error : undefined);

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
      <div className="grid gap-2">
        <pre aria-label="Command to run" className="whitespace-pre-wrap break-all rounded-md bg-surface-2 p-2 font-mono text-[13px]">
          {TOKEN_COMMAND}
        </pre>
        <CopyButton text={TOKEN_COMMAND} label="Copy command" failed="Select the command and copy it." />
      </div>
      {needed === null && !error ? (
        <p aria-busy="true" className="text-sm text-muted">
          Loading…
        </p>
      ) : (
        <form onSubmit={submit} className="grid gap-4">
          <Field id="token" label="Setup token" error={on("token")} autoComplete="off" required maxLength={128} spellCheck={false} />
          <Field id="username" label="User name" error={on("username")} autoComplete="username" required maxLength={64} autoCapitalize="none" spellCheck={false} hint="1 to 64 of a-z, 0-9, '.', '_' and '-'." />
          <Field id="display_name" label="Display name (optional)" autoComplete="name" maxLength={128} />
          <PasswordField id="password" label="Password" error={on("password")} autoComplete="new-password" hint="12 to 128 characters. Common passwords are refused." />
          <PasswordField id="password2" label="Password again" error={on("password2")} autoComplete="new-password" />
          {!field && <FormError error={error} />}
          <Button type="submit" disabled={busy}>
            {busy ? "Creating…" : "Continue"}
          </Button>
        </form>
      )}
    </section>
  );
}
