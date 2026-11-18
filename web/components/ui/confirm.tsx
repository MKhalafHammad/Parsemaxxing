"use client";

import { useState } from "react";

import { FormError } from "@/components/auth/fields";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";

/** A second confirmation (copy.md "Confirmation dialogs"): Cancel has initial focus, the confirm button repeats the verb. */
export function Confirm({
  open,
  onClose,
  title,
  confirm,
  onConfirm,
  destructive = false,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  confirm: string;
  onConfirm: (form: FormData) => Promise<void>;
  destructive?: boolean;
  children?: React.ReactNode;
}) {
  const [error, setError] = useState<string | Error>("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await onConfirm(new FormData(e.currentTarget));
      onClose();
    } catch (err) {
      setError(err as Error);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      open={open}
      onClose={() => {
        setError("");
        onClose();
      }}
      role="alertdialog"
      title={title}
    >
      <form onSubmit={submit} className="grid gap-4">
        {children}
        <FormError error={error} />
        <div className="flex justify-end gap-2">
          <Button type="button" data-autofocus variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={busy} variant={destructive ? "destructive" : "default"}>
            {confirm}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
