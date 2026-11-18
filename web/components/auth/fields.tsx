"use client";

import { Eye, EyeOff } from "lucide-react";
import { useState } from "react";

import { ErrorText } from "@/components/ui/error-text";
import { Input, Label } from "@/components/ui/input";

/** A labelled field with an optional hint; paste and password managers always work. */
export function Field({
  id,
  label,
  hint,
  ...props
}: { id: string; label: string; hint?: string } & React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <div className="grid gap-1">
      <Label htmlFor={id}>{label}</Label>
      <Input id={id} name={id} aria-describedby={hint ? `${id}-hint` : undefined} {...props} />
      {hint && (
        <p id={`${id}-hint`} className="text-[13px] text-subtle">
          {hint}
        </p>
      )}
    </div>
  );
}

/** A password field with a show/hide toggle. */
export function PasswordField({ id, label, hint, autoComplete }: { id: string; label: string; hint?: string; autoComplete: string }) {
  const [shown, setShown] = useState(false);
  return (
    <div className="grid gap-1">
      <Label htmlFor={id}>{label}</Label>
      <div className="flex gap-2">
        <Input id={id} name={id} type={shown ? "text" : "password"} autoComplete={autoComplete} required maxLength={1024} aria-describedby={hint ? `${id}-hint` : undefined} />
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
      {hint && (
        <p id={`${id}-hint`} className="text-[13px] text-subtle">
          {hint}
        </p>
      )}
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
