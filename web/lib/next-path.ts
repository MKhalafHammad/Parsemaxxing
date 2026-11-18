// Where to go after sign-in. Only a same-origin path is accepted: an absolute URL,
// a protocol-relative "//host", "/\host" (browsers read "\" as "/") or control characters
// fall back to the Overview, so a crafted ?next= link can't send a user to another site.
export function safeNext(raw: string | null | undefined): string {
  if (!raw || !raw.startsWith("/") || /^\/[/\\]/.test(raw) || /[\u0000-\u001f\u007f\\]/.test(raw)) return "/";
  const base = "http://pmx.invalid";
  try {
    const u = new URL(raw, base);
    if (u.origin !== base) return "/";
    return u.pathname + u.search + u.hash;
  } catch {
    return "/";
  }
}

/** The sign-in page URL that returns here afterwards. */
export const loginUrl = (next: string, ended = false) =>
  `/login?next=${encodeURIComponent(safeNext(next))}${ended ? "&ended=1" : ""}`;

/** The page a session in this stage must see next. */
export function stagePath(stage: string, next: string): string {
  const n = encodeURIComponent(safeNext(next));
  if (stage === "mfa") return `/login/mfa?next=${n}`;
  if (stage === "enrol") return `/mfa/enrol?next=${n}`;
  return safeNext(next);
}
