import { expect, test, type APIResponse } from "@playwright/test";

// The real Next.js server and proxy (no mocks): refusals happen before anything reaches the
// engine. ENGINE_URL points at a closed port, so a request that IS forwarded gets 502.
const SAME = { Origin: "http://localhost:3100", "X-Parsemaxxing": "1" };
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

/** The proxy's own refusals use the engine's error envelope, with a fresh request id in the body and header. */
async function envelope(r: APIResponse, code: string, message: string) {
  const body = await r.json();
  expect(body).toEqual({ error: { code, message, request_id: expect.stringMatching(UUID) }, detail: message });
  expect(r.headers()["x-request-id"]).toBe(body.error.request_id);
  return body.error.request_id as string;
}

test("DNS rebinding: an unknown Host is refused on pages and the API", async ({ request }) => {
  for (const path of ["/", "/runs/abcd1234", "/api/engine/runs", "/api/engine/admin/status"]) {
    const r = await request.get(path, { headers: { Host: "rebind.attacker.example:3100" } });
    expect(r.status(), path).toBe(421);
  }
  const post = await request.post("/api/engine/runs/abcd1234/approve", {
    headers: { ...SAME, Host: "rebind.attacker.example:3100", Origin: "http://rebind.attacker.example:3100" },
    data: { sha256: "a".repeat(64) },
  });
  expect(post.status()).toBe(421);
  await envelope(post, "misdirected_request", "unknown host");
});

test("cross-site state changes are refused", async ({ request }) => {
  const data = { sha256: "a".repeat(64) };
  const noHeader = await request.post("/api/engine/runs/abcd1234/approve", { headers: { Origin: SAME.Origin }, data });
  expect(noHeader.status()).toBe(403);
  await envelope(noHeader, "forbidden", "cross-site request refused");
  const foreign = await request.post("/api/engine/runs/abcd1234/approve", {
    headers: { ...SAME, Origin: "https://evil.example.com" },
    data,
  });
  expect(foreign.status()).toBe(403);
  const noOrigin = await request.post("/api/engine/runs/abcd1234/approve", { headers: { "X-Parsemaxxing": "1" }, data });
  expect(noOrigin.status()).toBe(403);
  // Positive control: the same request from the UI's own origin is forwarded (closed engine: 502).
  const ok = await request.post("/api/engine/runs/abcd1234/approve", { headers: SAME, data });
  expect(ok.status()).toBe(502);
  await envelope(ok, "bad_gateway", "the engine is not reachable");
});

test("only allowlisted engine paths are forwarded, however they are spelled", async ({ request }) => {
  const paths = ["admin%2F..%2Fruns", "runs/ABC", "docs", "runs/abcd1234/record", "openapi.json",
    "runs/abcd1234%2Fapprove", "runs%2Fabcd1234%2Fapprove", "RUNS/abcd1234/approve"];
  // ("runs//x/approve" is collapsed to "runs/x/approve" before any app code sees it: the same
  // allowlisted endpoint, so it is not tested as a bypass.)
  for (const path of paths) {
    expect((await request.get(`/api/engine/${path}`)).status(), `GET ${path}`).toBe(404);
    expect((await request.post(`/api/engine/${path}`, { headers: SAME })).status(), `POST ${path}`).toBe(404);
  }
  expect((await request.get("/api/engine/runs")).status()).toBe(502); // allowlisted: forwarded
  await envelope(await request.get("/api/engine/docs"), "not_found", "not found");
});

test("every proxy error gets its own request id, never one supplied by the client", async ({ request }) => {
  const headers = { "X-Request-ID": "client-chosen-id" };
  const a = await envelope(await request.get("/api/engine/runs", { headers }), "bad_gateway", "the engine is not reachable");
  const b = await envelope(await request.get("/api/engine/runs", { headers }), "bad_gateway", "the engine is not reachable");
  expect(a).not.toBe(b);
});

test("pages and the API carry security headers, with a nonce instead of unsafe-inline", async ({ request }) => {
  const page = await request.get("/");
  const csp = page.headers()["content-security-policy"] ?? "";
  expect(csp).toMatch(/script-src 'self' 'nonce-[A-Za-z0-9+/=]+' 'strict-dynamic'/);
  expect(csp).not.toContain("script-src 'self' 'unsafe-inline'");
  expect(csp).toContain("frame-ancestors 'none'");
  expect(page.headers()["x-frame-options"]).toBe("DENY");
  expect(page.headers()["x-powered-by"]).toBeUndefined();
  const second = (await request.get("/")).headers()["content-security-policy"];
  expect(second).not.toBe(csp); // a fresh nonce per request
  const api = await request.get("/api/engine/runs");
  expect(api.headers()["x-content-type-options"]).toBe("nosniff");
});
