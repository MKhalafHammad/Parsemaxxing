"use client";

import { Copy, Download } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";

/** Recovery codes, shown once: Copy, Download, and Continue only after "I have saved these codes". */
export function RecoveryCodes({ codes, onDone }: { codes: string[]; onDone: () => void }) {
  const [saved, setSaved] = useState(false);
  const [copied, setCopied] = useState("");
  const text = codes.join("\n") + "\n";

  function download() {
    const url = URL.createObjectURL(new Blob([text], { type: "text/plain" }));
    const a = Object.assign(document.createElement("a"), { href: url, download: "parsemaxxing-recovery-codes.txt" });
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <section aria-labelledby="codes-title" className="grid gap-3">
      <h2 id="codes-title" className="text-base font-semibold">
        Your recovery codes
      </h2>
      <p className="text-sm">You won&apos;t see these codes again. Each one signs you in once if you lose your authenticator.</p>
      <ul aria-label="Recovery codes" className="grid grid-cols-2 gap-1 rounded-md bg-surface-2 p-3 font-mono text-sm">
        {codes.map((c) => (
          <li key={c}>{c}</li>
        ))}
      </ul>
      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => navigator.clipboard.writeText(text).then(() => setCopied("Copied."), () => setCopied("Copy failed. Select the codes and copy them."))}
        >
          <Copy aria-hidden className="h-4 w-4" /> Copy
        </Button>
        <Button type="button" variant="outline" size="sm" onClick={download}>
          <Download aria-hidden className="h-4 w-4" /> Download
        </Button>
        <span role="status" className="text-sm text-muted">
          {copied}
        </span>
      </div>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={saved} onChange={(e) => setSaved(e.target.checked)} className="h-4 w-4" />I have saved these codes
      </label>
      <Button type="button" disabled={!saved} onClick={onDone} className="justify-self-start">
        Continue
      </Button>
    </section>
  );
}
