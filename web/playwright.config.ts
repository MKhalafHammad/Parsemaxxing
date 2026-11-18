import { defineConfig } from "@playwright/test";

// End-to-end tests against the production build. Engine responses are mocked in the browser,
// so no engine, Splunk or model is needed; the proxy tests hit the real Next.js server. It runs the
// standalone server.js exactly as the Dockerfile does (static assets copied beside it).
export default defineConfig({
  testDir: "e2e",
  timeout: 30_000,
  use: {
    baseURL: "http://localhost:3100",
    trace: "retain-on-failure",
    // A session cookie, so proxy.ts lets pages render; /auth/me is mocked in e2e/fixtures.ts.
    storageState: {
      cookies: [{ name: "__Host-pmx_session", value: "e2e-session", domain: "localhost", path: "/", expires: -1, httpOnly: true, secure: true, sameSite: "Strict" }],
      origins: [],
    },
  },
  webServer: [{
    command: "cp -r .next/static .next/standalone/.next/ && node .next/standalone/server.js",
    url: "http://localhost:3100",
    reuseExistingServer: false,
    env: {
      PORT: "3100",
      HOSTNAME: "127.0.0.1",
      ENGINE_URL: "http://127.0.0.1:9",
      NEXT_TELEMETRY_DISABLED: "1",
      ALLOWED_HOSTS: "localhost:3100",
      WEB_ORIGINS: "http://localhost:3100",
    },
  },
  // A second server for e2e/proxy-hop.spec.ts: its engine is an echo server the test runs on 3199,
  // and it trusts X-Forwarded-For only with the X-Pmx-Hop value in e2e/proxy-hop.txt.
  {
    command: "node .next/standalone/server.js",
    url: "http://localhost:3101/login",
    reuseExistingServer: false,
    env: {
      PORT: "3101",
      HOSTNAME: "127.0.0.1",
      ENGINE_URL: "http://127.0.0.1:3199",
      NEXT_TELEMETRY_DISABLED: "1",
      ALLOWED_HOSTS: "localhost:3101",
      WEB_ORIGINS: "http://localhost:3101",
      PMX_PROXY_HOP_FILE: "e2e/proxy-hop.txt",
    },
  }],
});
