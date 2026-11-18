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

test("a page without a session cookie redirects to sign-in; (auth) pages and the API do not", async ({ playwright }) => {
  const anon = await playwright.request.newContext({ baseURL: "http://localhost:3100", storageState: { cookies: [], origins: [] } });
  const r = await anon.get("/runs/abcd1234?phase=cim", { maxRedirects: 0 });
  expect(r.status()).toBe(307);
  expect(r.headers()["location"]).toMatch(/\/login\?next=%2Fruns%2Fabcd1234%3Fphase%3Dcim$/);
  for (const path of ["/login", "/login/mfa", "/login/recovery", "/setup", "/mfa/enrol"]) {
    expect((await anon.get(path, { maxRedirects: 0 })).status(), path).toBe(200);
  }
  expect((await anon.get("/api/engine/auth/me", { maxRedirects: 0 })).status()).toBe(502); // forwarded
  await anon.dispose();
});

test("the auth routes are allowlisted with their methods and id shapes", async ({ request }) => {
  const id = "00000000-0000-4000-8000-000000000001";
  const forwarded = [
    ["GET", "setup"], ["POST", "setup"], ["POST", "auth/login"], ["POST", "auth/login/mfa"], ["POST", "auth/logout"],
    ["GET", "auth/me"], ["POST", "auth/password"], ["POST", "auth/mfa/enrol"], ["POST", "auth/mfa/confirm"],
    ["POST", "auth/mfa/disable"], ["POST", "auth/mfa/recovery-codes"], ["GET", "auth/sessions"],
    ["POST", `auth/sessions/${id}/revoke`], ["POST", "auth/sessions/revoke-all"], ["GET", "auth/tokens"],
    ["POST", "auth/tokens"], ["POST", `auth/tokens/${id}/revoke`], ["GET", "auth/users"], ["POST", "auth/users"],
    ["POST", `auth/users/${id}/role`], ["POST", `auth/users/${id}/disable`], ["POST", `auth/users/${id}/enable`],
    ["POST", `auth/users/${id}/sessions/revoke`], ["GET", "audit"],
  ];
  for (const [method, path] of forwarded) {
    const r = await request.fetch(`/api/engine/${path}`, { method, headers: SAME });
    expect(r.status(), `${method} ${path}`).toBe(502);
  }
  const refused = [
    ["GET", "auth/login"], ["POST", "auth/me"], ["POST", "audit"], ["POST", "auth/users/not-a-uuid/role"],
    ["POST", `auth/users/${id}/delete`], ["POST", "auth/tokens/0000000A-0000-4000-8000-00000000000B/revoke"], ["GET", "health"],
  ];
  for (const [method, path] of refused) {
    const r = await request.fetch(`/api/engine/${path}`, { method, headers: SAME });
    expect(r.status(), `${method} ${path}`).toBe(404);
  }
  // A sign-in from another site is refused like any other state change.
  const foreign = await request.post("/api/engine/auth/login", { headers: { ...SAME, Origin: "https://evil.example.com" }, data: {} });
  expect(foreign.status()).toBe(403);
});
