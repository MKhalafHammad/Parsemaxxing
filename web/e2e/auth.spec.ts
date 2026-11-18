import type { Page, Route } from "@playwright/test";

import { expect, mockRun, run, signedInAs, test, user } from "./fixtures";

const LOGIN_FAILED = "Sign-in failed. Check your user name and password.";
const envelope = (status: number, message: string) => ({
  status,
  json: { error: { code: "e", message, request_id: "rid-1" }, detail: message },
});
const CODES = Array.from({ length: 10 }, (_, i) => `rc${i}-abcd-efgh`);

async function login(page: Page, stage: string, next = "") {
  await page.route("**/api/engine/setup", (r) => r.fulfill({ json: { needed: false } }));
  await page.route("**/api/engine/auth/login", (r) => r.fulfill({ json: { stage, user: user("admin") } }));
  await page.goto(`/login${next}`);
  await page.getByLabel("User name").fill("avery");
  await page.getByLabel("Password", { exact: true }).fill("correct horse battery");
  await page.getByRole("button", { name: "Sign in" }).click();
}

test.describe("without a session cookie", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("an app page redirects to sign-in with a same-origin next", async ({ page }) => {
    await page.route("**/api/engine/setup", (r) => r.fulfill({ json: { needed: false } }));
    await page.goto("/runs/e2e00001?phase=cim");
    await expect(page).toHaveURL(/\/login\?next=%2Fruns%2Fe2e00001%3Fphase%3Dcim$/);
    await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  });

  test("no admin yet: sign-in sends you to setup, which creates the admin and asks for MFA", async ({ page }) => {
    let body: Record<string, unknown> = {};
    await page.route("**/api/engine/setup", (r: Route) => {
      if (r.request().method() === "GET") return r.fulfill({ json: { needed: true } });
      body = JSON.parse(r.request().postData() ?? "{}");
      return r.fulfill({ status: 201, json: { stage: "enrol", user: user("admin", { mfa: false }) } });
    });
    await page.route("**/api/engine/auth/mfa/enrol", (r) => r.fulfill({ json: { secret: "JBSWY3DPEHPK3PXP", otpauth_uri: "otpauth://totp/Parsemaxxing:avery?secret=JBSWY3DPEHPK3PXP" } }));
    await page.goto("/login");
    await expect(page).toHaveURL(/\/setup$/);
    await page.getByLabel("Setup token").fill(" tok-123 ");
    await page.getByLabel("User name").fill("avery");
    await page.getByLabel("Password", { exact: true }).fill("a long enough password");
    await page.getByRole("textbox", { name: "Password again" }).fill("a different password!");
    await page.getByRole("button", { name: "Continue" }).click();
    await expect(page.getByRole("main").getByRole("alert")).toContainText("The two passwords don't match");
    await page.getByRole("textbox", { name: "Password again" }).fill("a long enough password");
    await page.getByRole("button", { name: "Continue" }).click();
    await expect(page).toHaveURL(/\/mfa\/enrol\?next=%2F$/);
    expect(body).toEqual({ token: "tok-123", username: "avery", display_name: "", password: "a long enough password" });
  });
});

test("a wrong password shows one generic message", async ({ page }) => {
  await page.route("**/api/engine/setup", (r) => r.fulfill({ json: { needed: false } }));
  await page.route("**/api/engine/auth/login", (r) => r.fulfill(envelope(401, LOGIN_FAILED)));
  await page.goto("/login");
  await page.getByLabel("User name").fill("nobody");
  await page.getByLabel("Password", { exact: true }).fill("wrong");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("main").getByRole("alert")).toContainText(LOGIN_FAILED);
  await expect(page).toHaveURL(/\/login$/); // no redirect loop on the login's own 401
});

test("a locked-out sign-in says how long to wait", async ({ page }) => {
  await page.route("**/api/engine/setup", (r) => r.fulfill({ json: { needed: false } }));
  await page.route("**/api/engine/auth/login", (r) => r.fulfill({ ...envelope(429, "Too many attempts. Try again in 2 minutes."), headers: { "Retry-After": "120" } }));
  await page.goto("/login");
  await page.getByLabel("User name").fill("avery");
  await page.getByLabel("Password", { exact: true }).fill("x");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("main").getByRole("alert")).toContainText("Try again in 2 minutes.");
});

test("MFA step: the code field, then back to next", async ({ page }) => {
  let sent: unknown = null;
  await page.route("**/api/engine/auth/login/mfa", (r) => {
    sent = JSON.parse(r.request().postData() ?? "{}");
    return r.fulfill({ json: { stage: "full", user: user("admin") } });
  });
  await page.route("**/api/engine/tas", (r) => r.fulfill({ json: [] }));
  await login(page, "mfa", "?next=%2Ftas");
  await expect(page).toHaveURL(/\/login\/mfa\?next=%2Ftas$/);
  const code = page.getByLabel("6-digit code");
  await expect(code).toHaveAttribute("autocomplete", "one-time-code");
  await expect(code).toHaveAttribute("inputmode", "numeric");
  await code.fill("123456");
  await page.getByRole("button", { name: "Verify" }).click();
  await expect(page).toHaveURL(/\/tas$/);
  expect(sent).toEqual({ code: "123456" });
});

test("a wrong MFA code stays on the step with the engine's message", async ({ page }) => {
  await page.route("**/api/engine/auth/login/mfa", (r) => r.fulfill(envelope(401, "That code didn't work. Try again.")));
  await login(page, "mfa");
  await page.getByLabel("6-digit code").fill("000000");
  await page.getByRole("button", { name: "Verify" }).click();
  await expect(page.getByRole("main").getByRole("alert")).toContainText("That code didn't work. Try again.");
  await expect(page).toHaveURL(/\/login\/mfa/);
});

test("a recovery code signs in and the shell says how many are left", async ({ page }) => {
  let sent: unknown = null;
  await page.route("**/api/engine/auth/login/mfa", (r) => {
    sent = JSON.parse(r.request().postData() ?? "{}");
    return r.fulfill({ json: { stage: "full", user: user("admin"), recovery_codes_left: 9 } });
  });
  await page.route("**/api/engine/runs", (r) => r.fulfill({ json: [] }));
  await page.route("**/api/engine/tas", (r) => r.fulfill({ json: [] }));
  await login(page, "mfa");
  await page.getByRole("link", { name: "Use a recovery code instead" }).click();
  await page.getByRole("textbox", { name: "Recovery code" }).fill("rc0-abcd-efgh");
  await page.getByRole("button", { name: "Verify" }).click();
  await expect(page.getByText("You used a recovery code. 9 are left.")).toBeVisible();
  expect(sent).toEqual({ recovery_code: "rc0-abcd-efgh" });
});

test("a session that needs enrolment is sent to /mfa/enrol; recovery codes are shown once", async ({ page }) => {
  await page.route("**/api/engine/auth/mfa/enrol", (r) => r.fulfill({ json: { secret: "JBSWY3DPEHPK3PXP", otpauth_uri: "otpauth://totp/Parsemaxxing:avery?secret=JBSWY3DPEHPK3PXP" } }));
  await page.route("**/api/engine/auth/mfa/confirm", (r) => r.fulfill({ json: { stage: "full", user: user("admin"), recovery_codes: CODES } }));
  await page.route("**/api/engine/tas", (r) => r.fulfill({ json: [] }));
  await signedInAs(page, "admin", "enrol");
  await page.goto("/tas");
  await expect(page).toHaveURL(/\/mfa\/enrol\?next=%2Ftas$/);
  await expect(page.getByLabel("Setup key")).toHaveText("JBSWY3DPEHPK3PXP");
  await page.getByText("Show the setup link").click();
  await expect(page.getByLabel("Setup link")).toContainText("otpauth://totp/");
  await page.getByLabel("6-digit code").fill("123456");
  await page.getByRole("button", { name: "Turn on MFA" }).click();

  await expect(page.getByRole("list", { name: "Recovery codes" }).getByRole("listitem")).toHaveCount(10);
  await expect(page.getByText("JBSWY3DPEHPK3PXP")).toHaveCount(0); // the secret left with the step
  const cont = page.getByRole("button", { name: "Continue" });
  await expect(cont).toBeDisabled();
  await page.getByLabel("I have saved these codes").check();
  await signedInAs(page, "admin");
  await cont.click();
  await expect(page).toHaveURL(/\/tas$/);
  expect(await page.content()).not.toContain(CODES[0]);
  expect(await page.evaluate(() => [localStorage.length, sessionStorage.length, document.cookie])).toEqual([0, 0, ""]);
});

test("next refuses anything that is not a same-origin path", async ({ page }) => {
  await page.route("**/api/engine/runs", (r) => r.fulfill({ json: [] }));
  await page.route("**/api/engine/tas", (r) => r.fulfill({ json: [] }));
  for (const next of ["https://evil.example.com/x", "//evil.example.com/x", "/\\evil.example.com", "javascript:alert(1)", "/\r\n//evil.example.com"]) {
    await login(page, "full", `?next=${encodeURIComponent(next)}`);
    await expect(page, next).toHaveURL("http://localhost:3100/");
    await expect(page.getByRole("heading", { name: "Runs", exact: true })).toBeVisible();
  }
});

test("a session that ended mid-use returns to sign-in with a message", async ({ page }) => {
  await page.route("**/api/engine/auth/me", (r) => r.fulfill(envelope(401, "Your session ended. Sign in again.")));
  await page.route("**/api/engine/setup", (r) => r.fulfill({ json: { needed: false } }));
  await page.goto("/tas");
  await expect(page).toHaveURL(/\/login\?next=%2Ftas&ended=1$/);
  await expect(page.getByRole("status")).toContainText("Your session ended.");
});

test("sign out ends the session and returns to sign-in", async ({ page }) => {
  let out = 0;
  await page.route("**/api/engine/auth/logout", (r) => {
    out++;
    expect(r.request().headers()["x-parsemaxxing"]).toBe("1");
    return r.fulfill({ json: { signed_out: true } });
  });
  await page.route("**/api/engine/tas", (r) => r.fulfill({ json: [] }));
  await page.route("**/api/engine/setup", (r) => r.fulfill({ json: { needed: false } }));
  await page.goto("/tas");
  await expect(page.getByText("Admin", { exact: true })).toBeVisible(); // role badge
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login$/);
  expect(out).toBe(1);
});

test("a viewer sees every admin action disabled with Admin only", async ({ page }) => {
  await signedInAs(page, "viewer");
  await page.route("**/api/engine/runs", (r) => r.fulfill({ json: [] }));
  await page.route("**/api/engine/tas", (r) => r.fulfill({ json: [] }));
  await page.goto("/");
  await expect(page.getByText("Viewer", { exact: true })).toBeVisible();
  const newRun = page.getByRole("button", { name: "New run" });
  await expect(newRun).toHaveAttribute("aria-disabled", "true");
  await expect(newRun).toHaveAccessibleDescription("Admin only");
  await newRun.click({ force: true }); // Playwright waits for aria-disabled controls; force proves a click does nothing
  await expect(page.getByRole("dialog")).toHaveCount(0);

  await mockRun(page, run("awaiting_approval"));
  await page.goto("/runs/e2e00001");
  for (const name of ["Approve…", "Reject…"]) {
    const b = page.getByRole("button", { name });
    await expect(b).toHaveAttribute("aria-disabled", "true");
    await expect(b).toHaveAccessibleDescription("Admin only");
    await b.click({ force: true });
    await expect(page.getByRole("alertdialog")).toHaveCount(0);
  }

  let confirmed = false;
  await page.route("**/api/engine/runs/e2e00001/profile", (r) => ((confirmed = true), r.fulfill({ json: {} })));
  await page.route("**/api/engine/runs/e2e00001/events*", (r) => r.fulfill({ json: [] }));
  await mockRun(page, run("profile_review"));
  await page.goto("/runs/e2e00001");
  const confirm = page.getByRole("button", { name: "Confirm profile" });
  await expect(confirm).toHaveAccessibleDescription("Admin only");
  await page.getByLabel("Vendor").press("Enter"); // implicit submission is refused too
  await confirm.click({ force: true });
  await expect(page.getByLabel("Vendor")).toHaveAttribute("readonly", "");
  expect(confirmed).toBe(false);

  await page.goto("/settings/users");
  await expect(page.getByRole("button", { name: "Add user" })).toHaveAccessibleDescription("Admin only");
  await expect(page.getByText("Only admins can see the user list.")).toBeVisible();
});

test("an API token is shown once, with Copy and a close-without-copying check", async ({ page }) => {
  const SECRET = "pmxt_e2eSecretValue0123456789";
  let list: object[] = [];
  let created: Record<string, unknown> = {};
  await page.route("**/api/engine/auth/tokens", (r) => {
    if (r.request().method() === "GET") return r.fulfill({ json: list });
    created = JSON.parse(r.request().postData() ?? "{}");
    list = [{ id: "00000000-0000-4000-8000-0000000000aa", name: "ci-runner", role: "viewer", owner: "avery", created_at: "2026-11-19 10:00:00+00:00", expires_at: "2099-01-01 00:00:00+00:00", last_used_at: null, status: "active" }];
    return r.fulfill({ status: 201, json: { token: SECRET, id: "00000000-0000-4000-8000-0000000000aa", name: "ci-runner", role: "viewer", expires_at: "2026-12-19 10:00:00+00:00" } });
  });
  await page.goto("/settings/api-tokens");
  await expect(page.getByText("No API tokens yet.")).toBeVisible();
  await page.getByRole("button", { name: "Create token" }).click();
  await page.getByLabel("Name").fill("ci-runner");
  await expect(page.getByLabel("Expires in (days)")).toHaveAttribute("max", "90");
  await page.getByRole("dialog").getByRole("button", { name: "Create token" }).click();

  await expect(page.getByLabel("New token")).toHaveText(SECRET);
  await expect(page.getByRole("dialog")).toContainText("You won't see this token again.");
  expect(created).toEqual({ name: "ci-runner", role: "viewer", expires_in_days: 30 });
  await page.getByRole("button", { name: "Done" }).click();
  await expect(page.getByRole("main").getByRole("alert")).toContainText("Close without copying? The token can't be shown again.");
  await page.getByRole("button", { name: "Close without copying" }).click();
  await expect(page.getByRole("table", { name: "API tokens" })).toContainText("ci-runner");
  expect(await page.content()).not.toContain(SECRET);

  let revoked = false;
  await page.route("**/api/engine/auth/tokens/*/revoke", (r) => ((revoked = true), r.fulfill({ json: { revoked: true } })));
  await page.getByRole("button", { name: "Revoke… ci-runner" }).click();
  await expect(page.getByRole("alertdialog")).toContainText('Revoke token "ci-runner"?');
  await expect(page.getByRole("button", { name: "Cancel" })).toBeFocused();
  await page.getByRole("button", { name: "Revoke token" }).click();
  await expect.poll(() => revoked).toBe(true);
});

test("a viewer can create only viewer tokens", async ({ page }) => {
  await signedInAs(page, "viewer");
  await page.route("**/api/engine/auth/tokens", (r) => r.fulfill({ json: [] }));
  await page.goto("/settings/api-tokens");
  await page.getByRole("button", { name: "Create token" }).click();
  await expect(page.getByLabel("Role").locator("option")).toHaveText(["Viewer"]);
});

test("account security: change password, new recovery codes once, sign out everywhere", async ({ page }) => {
  const posts: string[] = [];
  await page.route("**/api/engine/auth/sessions", (r) =>
    r.fulfill({ json: [{ id: "00000000-0000-4000-8000-0000000000s1", created_at: "2026-11-19 09:00:00+00:00", last_seen_at: "2026-11-19 10:00:00+00:00", expires_at: "2026-11-19 21:00:00+00:00", ip: "192.0.2.10", user_agent: "Firefox on Linux", current: true }] }),
  );
  for (const path of ["password", "mfa/recovery-codes", "sessions/revoke-all"]) {
    await page.route(`**/api/engine/auth/${path}`, (r) => {
      posts.push(path);
      return r.fulfill({ json: path === "mfa/recovery-codes" ? { recovery_codes: CODES } : { stage: "full", user: user("admin") } });
    });
  }
  await page.route("**/api/engine/setup", (r) => r.fulfill({ json: { needed: false } }));
  await page.goto("/me/security");
  await expect(page.getByRole("table", { name: "Active sessions" })).toContainText("192.0.2.10");

  await page.getByLabel("Current password", { exact: true }).fill("old password here");
  await page.getByLabel("New password", { exact: true }).fill("new password here!");
  await page.getByRole("textbox", { name: "New password again" }).fill("new password here!");
  await page.getByRole("button", { name: "Change password" }).click();
  await expect(page.getByRole("status").first()).toContainText("Your other sessions were signed out.");

  await page.locator("#codes_password").fill("new password here!");
  await page.getByRole("button", { name: "Create new codes" }).click();
  await expect(page.getByRole("list", { name: "Recovery codes" }).getByRole("listitem")).toHaveCount(10);
  await page.getByLabel("I have saved these codes").check();
  await page.getByRole("button", { name: "Continue" }).click();
  expect(await page.content()).not.toContain(CODES[0]);

  await page.getByRole("button", { name: "Sign out everywhere" }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Sign out everywhere" }).click();
  await expect(page).toHaveURL(/\/login$/);
  expect(posts).toEqual(["password", "mfa/recovery-codes", "sessions/revoke-all"]);
});

test("admin: users list, add a user, change a role", async ({ page }) => {
  const posts: { path: string; body: unknown }[] = [];
  const viewer = user("viewer");
  await page.route("**/api/engine/auth/users", (r) => {
    if (r.request().method() === "GET") return r.fulfill({ json: [user("admin"), viewer] });
    posts.push({ path: "users", body: JSON.parse(r.request().postData() ?? "{}") });
    return r.fulfill({ status: 201, json: user("viewer", { username: "sam" }) });
  });
  await page.route("**/api/engine/auth/users/*/role", (r) => {
    posts.push({ path: new URL(r.request().url()).pathname, body: JSON.parse(r.request().postData() ?? "{}") });
    return r.fulfill({ json: viewer });
  });
  await page.goto("/settings/users");
  await expect(page.getByRole("table", { name: "Users" })).toContainText("riley");
  await page.getByLabel("Role", { exact: true }).selectOption("viewer");
  await expect(page.getByRole("table", { name: "Users" })).not.toContainText("avery");
  await page.getByLabel("Role", { exact: true }).selectOption("");

  await page.getByRole("button", { name: "Add user" }).click();
  await page.getByLabel("User name").fill("sam");
  await page.getByLabel("Temporary password", { exact: true }).fill("temporary password 1");
  await page.getByRole("dialog").getByRole("button", { name: "Add user" }).click();
  await expect(page.getByRole("status").first()).toContainText("Added sam.");

  await page.getByRole("button", { name: "Change role… riley" }).click();
  await page.getByRole("alertdialog").getByLabel("Role").selectOption("admin");
  await page.getByRole("button", { name: "Change role", exact: true }).click();
  await expect.poll(() => posts.length).toBe(2);
  expect(posts[0]).toEqual({ path: "users", body: { username: "sam", display_name: "", role: "viewer", password: "temporary password 1" } });
  expect(posts[1]).toEqual({ path: `/api/engine/auth/users/${viewer.id}/role`, body: { role: "admin" } });
});

test("audit log: read-only, filter by action in the URL, older pages", async ({ page }) => {
  const asked: string[] = [];
  const row = (id: number) => ({ id, at: "2026-11-19 10:00:00+00:00", actor: "avery", user_id: null, event: "login", outcome: id % 2 ? "success" : "failure", ip: "192.0.2.10", detail: {} });
  await page.route("**/api/engine/audit*", (r) => {
    const q = new URL(r.request().url()).searchParams;
    asked.push(q.toString());
    const before = Number(q.get("before") ?? 100);
    return r.fulfill({ json: Array.from({ length: before > 80 ? 26 : 3 }, (_, i) => row(before - 1 - i)) });
  });
  await page.goto("/settings/audit-log");
  const table = page.getByRole("table", { name: "Audit log" });
  await expect(table.getByRole("row")).toHaveCount(26); // header + 25
  await expect(table).toContainText("Success");
  await expect(table).toContainText("Failure");
  await expect(page.getByRole("button", { name: /edit|delete/i })).toHaveCount(0);
  await page.getByLabel("Action").selectOption("login");
  await expect(page).toHaveURL(/\?event=login$/);
  await page.getByRole("button", { name: "Older" }).click();
  await expect(page).toHaveURL(/\?event=login&before=75$/);
  await expect(table.getByRole("row")).toHaveCount(4);
  expect(asked).toContain("limit=26&event=login&before=75");
});
