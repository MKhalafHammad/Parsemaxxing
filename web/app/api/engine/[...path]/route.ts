// Server-side proxy to the engine. The browser never learns ENGINE_URL, and only these paths
// and methods pass. State changes must come from this app's own pages: a same-origin Origin
// and the custom header are both required, and the engine checks its header again.
import { NextRequest } from "next/server";

import { errorResponse } from "@/lib/error-envelope";
import { allowedHost, allowedOrigin } from "@/lib/hosts";

const ENGINE_URL = process.env.ENGINE_URL ?? "http://127.0.0.1:8080";
const JOB = "[a-z0-9]{4,16}";
const ROUTES: { method: string; pattern: RegExp }[] = [
  { method: "GET", pattern: /^runs$/ },
  { method: "GET", pattern: new RegExp(`^runs/${JOB}$`) },
  { method: "GET", pattern: new RegExp(`^runs/${JOB}/(events|stream|package)$`) },
  { method: "GET", pattern: /^admin\/status$/ },
  { method: "GET", pattern: /^tas$/ },
  { method: "POST", pattern: /^uploads$/ },
  { method: "POST", pattern: new RegExp(`^runs/${JOB}/(profile|approve|reject)$`) },
  { method: "POST", pattern: /^admin\/kill$/ },
];

async function forward(req: NextRequest, path: string[]): Promise<Response> {
  // Segments arrive decoded: an encoded separator or dot segment is refused, not interpreted.
  const raw = new URL(req.url).pathname;
  if (
    /\/\/|%2f|%5c/i.test(raw) ||
    path.some((seg) => /[/\\]/.test(seg) || seg === "." || seg === ".." || seg === "")
  ) {
    return errorResponse(404, "not_found", "not found");
  }
  const target = path.join("/");
  if (!ROUTES.some((r) => r.method === req.method && r.pattern.test(target))) {
    return errorResponse(404, "not_found", "not found");
  }
  // Defence in depth with proxy.ts: a known Host on every request, and for state changes the
  // custom header plus an Origin from the fixed list (never one derived from Host).
  if (!allowedHost(req.headers.get("host"))) {
    return errorResponse(421, "misdirected_request", "unknown host");
  }
  if (req.method !== "GET") {
    if (req.headers.get("x-parsemaxxing") !== "1" || !allowedOrigin(req.headers.get("origin"))) {
      return errorResponse(403, "forbidden", "cross-site request refused");
    }
  }
  const headers: Record<string, string> = { "X-Parsemaxxing": "1" };
  for (const h of ["content-type", "content-length", "last-event-id"]) {
    const v = req.headers.get(h);
    if (v) headers[h] = v;
  }
  const url = `${ENGINE_URL}/${target}${req.nextUrl.search}`;
  let upstream: Response;
  try {
    upstream = await fetch(url, {
      method: req.method,
      headers,
      body: req.method === "GET" ? undefined : req.body,
      // @ts-expect-error Node fetch needs this to stream a request body
      duplex: "half",
      cache: "no-store",
      redirect: "manual",
      signal: req.signal,
    });
  } catch {
    return errorResponse(502, "bad_gateway", "the engine is not reachable");
  }
  const out = new Headers();
  for (const h of ["content-type", "content-disposition", "cache-control", "x-request-id"]) {
    const v = upstream.headers.get(h);
    if (v) out.set(h, v);
  }
  if (target.endsWith("/stream")) out.set("X-Accel-Buffering", "no");
  return new Response(upstream.body, { status: upstream.status, headers: out });
}

type Ctx = { params: Promise<{ path: string[] }> };
export async function GET(req: NextRequest, ctx: Ctx) {
  return forward(req, (await ctx.params).path);
}
export async function POST(req: NextRequest, ctx: Ctx) {
  return forward(req, (await ctx.params).path);
}
export const dynamic = "force-dynamic";
