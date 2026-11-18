"use client";

import { Copy } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";

/** Copy to the clipboard; a failed copy says how to recover (`failed`, e.g. "Select the key and copy it."). */
export function CopyButton({ text, failed, label = "Copy" }: { text: string; failed: string; label?: string }) {
  const [said, setSaid] = useState("");
  return (
    <span className="inline-flex flex-wrap items-center gap-2">
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={() => navigator.clipboard.writeText(text).then(() => setSaid("Copied."), () => setSaid(`Copy failed. ${failed}`))}
      >
        <Copy aria-hidden className="h-4 w-4" /> {label}
      </Button>
      <span role="status" className="text-sm text-muted">
        {said}
      </span>
    </span>
  );
}
