"use client";

import { LogOut, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { notice, SessionContext } from "@/components/auth/session";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ErrorText } from "@/components/ui/error-text";
import { api, ApiError, postJson, type Me } from "@/lib/api";
import { loginUrl, stagePath } from "@/lib/next-path";

const NAV = [
  { href: "/", label: "Runs" },
  { href: "/tas", label: "TA registry" },
  { href: "/settings/users", label: "Users" },
  { href: "/settings/api-tokens", label: "API tokens" },
  { href: "/settings/audit-log", label: "Audit log" },
];

/** The (app) shell: nothing inside renders until the engine says who is signed in. */
export function Shell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [recoveryLeft] = useState(() => {
    const n = notice.recoveryLeft;
    notice.recoveryLeft = null;
    return n;
  });

  useEffect(() => {
    const here = window.location.pathname + window.location.search;
    api<Me>("/auth/me")
      .then((m) => {
        if (m.stage !== "full") router.replace(stagePath(m.stage, here));
        else setMe(m);
      })
      .catch((e: Error) => {
        if (e instanceof ApiError && e.status === 401) router.replace(loginUrl(here, true));
        else setError(e);
      });
  }, [router]);

  async function signOut() {
    await postJson("/auth/logout", {}).catch(() => undefined); // the cookie is cleared either way
    router.replace("/login");
  }

  return (
    <SessionContext.Provider value={me}>
      <header className="glass-strong sticky top-0 z-30 border-x-0 border-t-0">
        <nav aria-label="Main" className="mx-auto flex max-w-[90rem] flex-wrap items-center gap-x-6 gap-y-1 px-4 py-3 sm:px-6">
          <Link href="/" className="bg-gradient-to-r from-[#c4b5fd] via-[#7dd3fc] to-[#f0abfc] bg-clip-text text-lg font-bold tracking-tight text-transparent">
            Parsemaxxing
          </Link>
          {NAV.map((n) => (
            <Link
              key={n.href}
              href={n.href}
              aria-current={pathname === n.href ? "page" : undefined}
              className="text-sm text-muted hover:text-fg aria-[current=page]:text-fg aria-[current=page]:underline"
            >
              {n.label}
            </Link>
          ))}
          {me && (
            <span className="ml-auto flex items-center gap-3 text-sm">
              <Badge variant={me.user.role === "admin" ? "running" : "default"}>{me.user.role === "admin" ? "Admin" : "Viewer"}</Badge>
              <Link href="/me/security" className="text-muted hover:text-fg" aria-current={pathname === "/me/security" ? "page" : undefined}>
                {me.user.display_name || me.user.username}
              </Link>
              <Button size="sm" variant="ghost" onClick={signOut}>
                <LogOut aria-hidden className="h-4 w-4" /> Sign out
              </Button>
            </span>
          )}
        </nav>
      </header>
      <main id="main" className="mx-auto max-w-[90rem] px-4 py-6 sm:px-6">
        {recoveryLeft !== null && me && (
          <div role="status" className="mb-4 flex flex-wrap items-center gap-2 rounded-md border border-warn bg-warn-bg p-3 text-sm">
            <TriangleAlert aria-hidden className="h-4 w-4 text-warn" />
            You used a recovery code. {recoveryLeft} {recoveryLeft === 1 ? "is" : "are"} left.
            <Link href="/me/security#recovery" className="underline underline-offset-2">
              Create new codes
            </Link>
          </div>
        )}
        {error ? (
          <div role="alert" className="glass p-4 text-sm text-bad">
            <p className="font-semibold">Parsemaxxing isn&apos;t responding.</p>
            <ErrorText error={error} />
            <Button className="mt-3" size="sm" variant="outline" onClick={() => window.location.reload()}>
              Try again
            </Button>
          </div>
        ) : me ? (
          children
        ) : (
          <p aria-busy="true" className="text-sm text-muted">
            Loading…
          </p>
        )}
      </main>
    </SessionContext.Provider>
  );
}
