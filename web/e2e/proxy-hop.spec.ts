import { createServer, type IncomingHttpHeaders, type Server } from "node:http";

import { expect, test } from "@playwright/test";

// The second web server (playwright.config.ts) forwards to this echo engine, which records the
// headers it receives. Only a request with the right X-Pmx-Hop passes X-Forwarded-For on.
const HOP = "e2e-test-hop-not-a-secret";
let engine: Server;
let seen: IncomingHttpHeaders = {};

test.beforeAll(async () => {
  engine = createServer((req, res) => {
    seen = req.headers;
    res.setHeader("content-type", "application/json");
    res.end("[]");
  });
  await new Promise<void>((ok) => engine.listen(3199, "127.0.0.1", ok));
});
test.afterAll(() => new Promise<void>((ok) => engine.close(() => ok())));

async function forwarded(request: import("@playwright/test").APIRequestContext, headers: Record<string, string>) {
  seen = {};
  const r = await request.get("http://localhost:3101/api/engine/runs", { headers });
  expect(r.status()).toBe(200);
  return seen;
}

test("a client-sent X-Forwarded-For is not forwarded without the proxy's hop secret", async ({ request }) => {
  for (const headers of <Record<string, string>[]>[
    { "X-Forwarded-For": "203.0.113.7" },
    { "X-Forwarded-For": "203.0.113.7", "X-Pmx-Hop": "wrong" },
    { "X-Forwarded-For": "203.0.113.7", "X-Pmx-Hop": HOP + "x" },
    { "X-Forwarded-For": "203.0.113.7", "X-Pmx-Hop": "" },
  ]) {
    const h = await forwarded(request, headers);
    expect(h["x-forwarded-for"], JSON.stringify(headers)).toBeUndefined();
    expect(h["x-pmx-hop"]).toBeUndefined();
  }
});

test("with the right hop secret the last X-Forwarded-For hop is forwarded, the secret is not", async ({ request }) => {
  const h = await forwarded(request, { "X-Forwarded-For": "198.51.100.1, 203.0.113.7", "X-Pmx-Hop": HOP });
  expect(h["x-forwarded-for"]).toBe("203.0.113.7");
  expect(h["x-pmx-hop"]).toBeUndefined();
});
