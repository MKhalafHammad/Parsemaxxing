"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";

import { Field, FormError, formValues } from "@/components/auth/fields";
import { RecoveryCodes } from "@/components/auth/recovery-codes";
import { Button } from "@/components/ui/button";
import { postJson } from "@/lib/api";
import { safeNext } from "@/lib/next-path";

type Enrolment = { secret: string; otpauth_uri: string };

function Enrol() {
  const router = useRouter();
  const next = safeNext(useSearchParams().get("next"));
  const [enrolment, setEnrolment] = useState<Enrolment | null>(null);
  const [codes, setCodes] = useState<string[] | null>(null);
  const [error, setError] = useState<string | Error>("");
  const [busy, setBusy] = useState(false);
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return; // one enrolment per visit (each call makes a new secret)
    started.current = true;
    postJson<Enrolment>("/auth/mfa/enrol", {}).then(setEnrolment, setError);
  }, []);

  async function confirm(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const r = await postJson<{ recovery_codes: string[] }>("/auth/mfa/confirm", { code: formValues(e)("code").trim() });
      setEnrolment(null); // the secret is no longer needed on screen
      setCodes(r.recovery_codes);
    } catch (err) {
      setError(err as Error);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby="enrol-title" className="glass grid gap-4 p-6">
      <h1 id="enrol-title" className="text-xl font-semibold">
        Set up MFA
      </h1>
      {codes ? (
        <RecoveryCodes
          codes={codes}
          onDone={() => {
            setCodes(null);
            router.replace(next);
          }}
        />
      ) : (
        <>
          <p className="text-sm text-muted">Add Parsemaxxing to your authenticator app, then enter the 6-digit code it shows.</p>
          {enrolment && (
            <>
              <div className="grid gap-1">
                <p className="text-sm font-medium">Setup key</p>
                <p aria-label="Setup key" className="break-all rounded-md bg-surface-2 p-2 font-mono text-sm">
                  {enrolment.secret}
                </p>
              </div>
              <details className="text-sm">
                <summary className="cursor-pointer">Show the setup link</summary>
                <p aria-label="Setup link" className="mt-1 break-all rounded-md bg-surface-2 p-2 font-mono text-[13px]">
                  {enrolment.otpauth_uri}
                </p>
              </details>
              <form onSubmit={confirm} className="grid gap-4">
                <Field id="code" label="6-digit code" autoComplete="one-time-code" inputMode="numeric" pattern="\d{6}" maxLength={6} required />
                <Button type="submit" disabled={busy}>
                  {busy ? "Verifying…" : "Turn on MFA"}
                </Button>
              </form>
            </>
          )}
          <FormError error={error} />
        </>
      )}
    </section>
  );
}

export default function EnrolPage() {
  return (
    <Suspense>
      <Enrol />
    </Suspense>
  );
}
