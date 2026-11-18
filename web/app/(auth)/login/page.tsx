"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { Field, FormError, formValues, PasswordField } from "@/components/auth/fields";
import { Button } from "@/components/ui/button";
import { api, postJson, type SignedIn } from "@/lib/api";
import { stagePath } from "@/lib/next-path";

function Login() {
  const router = useRouter();
  const params = useSearchParams();
  const next = params.get("next");
  const [error, setError] = useState<string | Error>("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api<{ needed: boolean }>("/setup")
      .then((s) => s.needed && router.replace("/setup"))
      .catch(() => undefined); // the form still works; sign-in reports an unreachable engine
  }, [router]);

  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const v = formValues(e);
    setBusy(true);
    setError("");
    try {
      const r = await postJson<SignedIn>("/auth/login", { username: v("username"), password: v("password") });
      router.replace(stagePath(r.stage, next ?? "/"));
    } catch (err) {
      setError(err as Error);
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby="login-title" className="glass grid gap-4 p-6">
      <h1 id="login-title" className="text-xl font-semibold">
        Sign in
      </h1>
      {params.get("ended") && (
        <p role="status" className="rounded-md bg-warn-bg p-2 text-sm">
          Your session ended. Sign in again; you will return to this page.
        </p>
      )}
      <form onSubmit={submit} className="grid gap-4">
        <Field id="username" label="User name" autoComplete="username" required maxLength={128} autoCapitalize="none" spellCheck={false} />
        <PasswordField id="password" label="Password" autoComplete="current-password" />
        <FormError error={error} />
        <Button type="submit" disabled={busy}>
          {busy ? "Signing in…" : "Sign in"}
        </Button>
      </form>
    </section>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <Login />
    </Suspense>
  );
}
