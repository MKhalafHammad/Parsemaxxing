"use client";

import { Eye, EyeOff } from "lucide-react";
import { useState } from "react";

import { ErrorText } from "@/components/ui/error-text";
import { Input, Label } from "@/components/ui/input";

type FieldError = string | Error | undefined;

/** aria-describedby and aria-invalid for a field's hint and its own error (copy.md "Error pattern"). */
function described(id: string, hint?: string, error?: FieldError) {
  const ids = [hint && `${id}-hint`, error && `${id}-error`].filter(Boolean).join(" ");
  return { "aria-describedby": ids || undefined, "aria-invalid": error ? true : undefined };
}

function Below({ id, hint, error }: { id: string; hint?: string; error?: FieldError }) {
  return (
    <>
      {hint && (
        <p id={`${id}-hint`} className="text-[13px] text-subtle">
          {hint}
        </p>
      )}
      {error && (
        <p id={`${id}-error`} role="alert" className="text-sm text-bad">
          <ErrorText error={error} />
        </p>
      )}
    </>
  );
}

/** A labelled field with an optional hint and error; paste and password managers always work. */
export function Field({
  id,
  label,
  hint,
  error,
  ...props
}: { id: string; label: string; hint?: string; error?: FieldError } & React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <div className="grid gap-1">
      <Label htmlFor={id}>{label}</Label>
      <Input id={id} name={id} {...described(id, hint, error)} {...props} />
      <Below id={id} hint={hint} error={error} />
    </div>
  );
}

/** The 6-digit MFA code: "123 456" pasted works (spaces are stripped by `mfaCode`). */
export function CodeField({ error, hint }: { error?: FieldError; hint?: string }) {
  return <Field id="code" label="6-digit code" hint={hint} error={error} autoComplete="one-time-code" inputMode="numeric" aria-required maxLength={32} spellCheck={false} />;
}

export const CODE_RULE = "Enter the 6 digits from your authenticator app.";
/** The code without spaces, or null when it is not 6 digits. */
export function mfaCode(raw: string): string | null {
  const c = raw.replace(/\s+/g, "");
  return /^\d{6}$/.test(c) ? c : null;
}

/** A password field with a show/hide toggle. */
export function PasswordField({ id, label, hint, autoComplete, error }: { id: string; label: string; hint?: string; autoComplete: string; error?: FieldError }) {
  const [shown, setShown] = useState(false);
  return (
    <div className="grid gap-1">
      <Label htmlFor={id}>{label}</Label>
      <div className="flex gap-2">
        <Input id={id} name={id} type={shown ? "text" : "password"} autoComplete={autoComplete} required maxLength={1024} {...described(id, hint, error)} />
        <button
          type="button"
          onClick={() => setShown(!shown)}
          aria-pressed={shown}
          aria-label={shown ? `Hide ${label.toLowerCase()}` : `Show ${label.toLowerCase()}`}
          className="rounded-md border border-line-strong px-2 text-muted hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus"
        >
          {shown ? <EyeOff aria-hidden className="h-4 w-4" /> : <Eye aria-hidden className="h-4 w-4" />}
        </button>
      </div>
      <Below id={id} hint={hint} error={error} />
    </div>
  );
}

export function FormError({ error }: { error: string | Error }) {
  if (!error) return null;
  return (
    <p role="alert" className="text-sm text-bad">
      <ErrorText error={error} />
    </p>
  );
}

/** A form's values by field name ("" when absent). */
export function formValues(e: React.FormEvent<HTMLFormElement>) {
  const f = new FormData(e.currentTarget);
  return (name: string) => String(f.get(name) ?? "");
}
