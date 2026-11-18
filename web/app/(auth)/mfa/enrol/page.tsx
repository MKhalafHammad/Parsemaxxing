"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";

import { SignInAsSomeoneElse } from "@/components/auth/code-form";
import { CODE_RULE, CodeField, FormError, formValues, mfaCode, PasswordField } from "@/components/auth/fields";
import { RecoveryCodes } from "@/components/auth/recovery-codes";
import { Button } from "@/components/ui/button";
import { CopyButton } from "@/components/ui/copy-button";
import { api, postJson, type Me } from "@/lib/api";
import { safeNext } from "@/lib/next-path";

type Enrolment = { secret: string; otpauth_uri: string };

function Enrol() {
  const router = useRouter();
  const next = safeNext(useSearchParams().get("next"));
  const [enrolment, setEnrolment] = useState<Enrolment | null>(null);
  const [codes, setCodes] = useState<string[] | null>(null);
  const [stage, setStage] = useState<Me["stage"] | null>(null);
  const [error, setError] = useState<string | Error>("");
  const [codeError, setCodeError] = useState<string | Error>("");
  const [busy, setBusy] = useState(false);
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return; // one enrolment per visit (each call makes a new secret)
    started.current = true;
    api<Me>("/auth/me").then((me) => {
      setStage(me.stage);
      // Forced enrolment right after sign-in needs no password; a full session re-authenticates first.
      if (me.stage === "enrol") postJson<Enrolment>("/auth/mfa/enrol", {}).then(setEnrolment, setError);
    }, setError);
  }, []);

  async function start(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      setEnrolment(await postJson<Enrolment>("/auth/mfa/enrol", { password: formValues(e)("enrol_password") }));
    } catch (err) {
      setError(err as Error);
    } finally {
      setBusy(false);
    }
  }

  async function confirm(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const code = mfaCode(formValues(e)("code"));
    if (!code) return setCodeError(CODE_RULE);
    setBusy(true);
    setCodeError("");
    try {
      const r = await postJson<{ recovery_codes: string[] }>("/auth/mfa/confirm", { code });
      setEnrolment(null); // the secret is no longer needed on screen
      setCodes(r.recovery_codes);
    } catch (err) {
      setCodeError(err as Error);
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
          <p className="text-sm text-muted">
            {stage === "enrol" && "Admins need MFA. Set it up to continue. "}
            Add Parsemaxxing to your authenticator app, then enter the 6-digit code it shows.
          </p>
          {stage === "full" && !enrolment && (
            <form onSubmit={start} className="grid gap-4">
              <PasswordField id="enrol_password" label="Current password" autoComplete="current-password" hint="Confirm it's you before setting up MFA." />
              <Button type="submit" disabled={busy}>
                {busy ? "Checking…" : "Continue"}
              </Button>
            </form>
          )}
          {enrolment && (
            <>
              <div className="grid gap-1">
                <p className="text-sm font-medium">Setup key</p>
                {/* Groups of 4 by spacing only, so the text (and a selection) is the key itself. */}
                <p aria-label="Setup key" className="break-all rounded-md bg-surface-2 p-2 font-mono text-sm">
                  {enrolment.secret.match(/.{1,4}/g)?.map((g, i) => (
                    <span key={i} className="mr-[1ch] inline-block">
                      {g}
                    </span>
                  ))}
                </p>
                <CopyButton text={enrolment.secret} label="Copy key" failed="Select the key and copy it." />
              </div>
              <details className="text-sm">
                <summary className="cursor-pointer">Show the setup link</summary>
                <p aria-label="Setup link" className="mt-1 break-all rounded-md bg-surface-2 p-2 font-mono text-[13px]">
                  {enrolment.otpauth_uri}
                </p>
              </details>
              <form onSubmit={confirm} className="grid gap-4">
                <CodeField error={codeError} />
                <Button type="submit" disabled={busy}>
                  {busy ? "Verifying…" : "Turn on MFA"}
                </Button>
              </form>
            </>
          )}
          <FormError error={error} />
          {stage === "enrol" && <SignInAsSomeoneElse />}
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
