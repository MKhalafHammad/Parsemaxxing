// Runs before every page and API request (Next.js 16 "proxy", formerly middleware).
// 1. Host allowlist: a DNS-rebinding page arrives with the attacker's host name and is refused
//    before anything renders or reaches the engine (threat T8.5).
// 2. A per-request CSP nonce, so scripts need no 'unsafe-inline' (Next.js attaches the nonce
//    to its own scripts).
// 3. A page outside (auth) with no session cookie goes to /login?next=<this path>. Only the
//    cookie's presence is checked here; the engine decides whether the session is valid.
import { NextResponse, type NextRequest } from "next/server";

import { errorResponse } from "@/lib/error-envelope";
import { allowedHost } from "@/lib/hosts";
import { loginUrl } from "@/lib/next-path";

const SESSION_COOKIE = "__Host-pmx_session";
const OPEN = /^\/(api\/|login(\/|$)|setup$|mfa\/enrol$)/; // (auth) pages and the engine proxy

export function proxy(req: NextRequest) {
  if (!allowedHost(req.headers.get("host"))) {
    return errorResponse(421, "misdirected_request", "unknown host");
  }
  if (!OPEN.test(req.nextUrl.pathname) && !req.cookies.has(SESSION_COOKIE)) {
    return NextResponse.redirect(new URL(loginUrl(req.nextUrl.pathname + req.nextUrl.search), req.url));
  }
  const nonce = Buffer.from(crypto.randomUUID()).toString("base64");
  const csp = [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data:",
    "connect-src 'self'",
    "font-src 'self'",
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'self'",
    "frame-ancestors 'none'",
  ].join("; ");
  const headers = new Headers(req.headers);
  headers.set("x-nonce", nonce);
  headers.set("Content-Security-Policy", csp);
  const res = NextResponse.next({ request: { headers } });
  res.headers.set("Content-Security-Policy", csp);
  return res;
}

export const config = {
  matcher: [{ source: "/((?!_next/static|_next/image|favicon.ico).*)" }],
};
