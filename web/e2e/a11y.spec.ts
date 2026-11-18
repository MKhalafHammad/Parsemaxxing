import { readFileSync } from "node:fs";
import { createRequire } from "node:module";

import type { Page } from "@playwright/test";

import { expect, signedInAs, test, user } from "./fixtures";

// axe-core is already in the tree (through eslint-plugin-jsx-a11y); no new dependency. It is
// evaluated through the DevTools protocol, which the page's CSP does not apply to.
const AXE = readFileSync(createRequire(__filename).resolve("axe-core/axe.min.js"), "utf8");

type Violation = { id: string; impact: string | null; nodes: { target: string[] }[] };
async function serious(page: Page): Promise<string[]> {
  await page.evaluate(AXE);
  const found = await page.evaluate(async () => {
    const axe = (window as unknown as { axe: { run: (c: Document, o: object) => Promise<{ violations: Violation[] }> } }).axe;
    const r = await axe.run(document, { runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"] } });
    return r.violations;
  });
  return found.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`);
}

async function mockAccount(page: Page) {
  await page.route("**/api/engine/setup", (r) => r.fulfill({ json: { needed: false } }));
  await page.route("**/api/engine/auth/sessions", (r) =>
    r.fulfill({ json: [{ id: "00000000-0000-4000-8000-0000000000s1", created_at: "2026-11-19 09:00:00+00:00", last_seen_at: "2026-11-19 10:00:00+00:00", expires_at: "2026-11-19 21:00:00+00:00", ip: "192.0.2.10", user_agent: "Firefox on Linux", current: true }] }),
  );
  await page.route("**/api/engine/auth/users", (r) => r.fulfill({ json: [user("admin"), user("viewer")] }));
  await page.route("**/api/engine/auth/tokens", (r) =>
    r.fulfill({ json: [{ id: "00000000-0000-4000-8000-0000000000aa", name: "ci-runner", role: "viewer", owner: "avery", created_at: "2026-11-19 10:00:00+00:00", expires_at: "2026-11-29 10:00:00+00:00", last_used_at: null, status: "active" }] }),
  );
  await page.route("**/api/engine/audit*", (r) =>
    r.fulfill({ json: [{ id: 1, at: "2026-11-19 10:00:00+00:00", actor: "avery", user_id: null, event: "login", outcome: "success", ip: "192.0.2.10", detail: {} }] }),
  );
  await page.route("**/api/engine/auth/mfa/enrol", (r) => r.fulfill({ json: { secret: "JBSWY3DPEHPK3PXP", otpauth_uri: "otpauth://totp/Parsemaxxing:avery?secret=JBSWY3DPEHPK3PXP" } }));
  await page.route("**/api/engine/runs", (r) => r.fulfill({ json: [] }));
  await page.route("**/api/engine/tas", (r) => r.fulfill({ json: [] }));
}

const PAGES: [string, string][] = [
  ["/login", "Sign in"],
  ["/login/mfa", "Enter your MFA code"],
  ["/login/recovery", "Use a recovery code"],
  ["/setup", "Setup is already complete"],
  ["/mfa/enrol", "Set up MFA"],
  ["/me/security", "Account security"],
  ["/settings/api-tokens", "API tokens"],
  ["/settings/users", "Users"],
  ["/settings/audit-log", "Audit log"],
  ["/", "Runs"],
];

for (const role of ["admin", "viewer"] as const) {
  test(`no serious or critical axe violations on the auth and account pages (${role})`, async ({ page }) => {
    await mockAccount(page);
    await signedInAs(page, role);
    for (const [path, heading] of PAGES) {
      await page.goto(path);
      await expect(page.getByRole("heading", { name: heading, level: 1 }), path).toBeVisible();
      expect(await serious(page), path).toEqual([]);
    }
  });
}
