"use client";

import { Lock } from "lucide-react";
import { cloneElement, createContext, useContext, useId, type ReactElement } from "react";

import type { Me } from "@/lib/api";
import { cn } from "@/lib/utils";

// Who is signed in, from GET /auth/me. Display only: the engine decides every request.
export const SessionContext = createContext<Me | null>(null);

export function useSession() {
  const me = useContext(SessionContext);
  return { me, isAdmin: me?.user.role === "admin" };
}

// A count carried from the MFA step into the shell for one banner (not a credential).
export const notice = { recoveryLeft: null as number | null };

type Actionable = ReactElement<{ className?: string; onClick?: unknown; "aria-describedby"?: string }>;

/** The one pattern for admin actions: viewers see the control disabled and labelled "Admin only". */
export function AdminOnly({ children }: { children: Actionable }) {
  const { isAdmin } = useSession();
  const id = useId();
  if (isAdmin) return children;
  return (
    <span className="inline-flex flex-wrap items-center gap-2">
      {cloneElement(children, {
        "aria-disabled": true,
        "aria-describedby": id,
        title: "Admin only",
        // aria-disabled keeps it focusable so the reason can be found; the click does nothing.
        onClick: (e: React.MouseEvent) => e.preventDefault(),
        className: cn(children.props.className, "cursor-not-allowed opacity-50"),
      } as Record<string, unknown>)}
      <span id={id} className="inline-flex items-center gap-1 text-[13px] text-muted">
        <Lock aria-hidden className="h-3.5 w-3.5" /> Admin only
      </span>
    </span>
  );
}
