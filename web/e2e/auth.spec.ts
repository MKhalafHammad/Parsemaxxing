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

test("Turn off MFA is replaced by the rule for admins who must use MFA, and offered to viewers", async ({ page }) => {
  await page.route("**/api/engine/auth/sessions", (r) => r.fulfill({ json: [] }));
  for (const [me, shown] of [
    [{ user: user("admin"), stage: "full", via: "session", mfa_required: true }, false],
    [{ user: user("admin"), stage: "full", via: "session" }, false], // older engine: no flag, an admin counts as required
    [{ user: user("viewer", { mfa: true }), stage: "full", via: "session", mfa_required: false }, true],
  ] as const) {
    await page.route("**/api/engine/auth/me", (r) => r.fulfill({ json: me }));
    await page.goto("/me/security");
    await expect(page.getByRole("heading", { name: "Account security" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Turn off MFA…" })).toHaveCount(shown ? 1 : 0);
    await expect(page.getByText("MFA is required for admins.")).toHaveCount(shown ? 0 : 1);
  }
});

test("Sign in as someone else leaves the MFA step, the recovery step and forced enrolment", async ({ page }) => {
  let out = 0;
  await page.route("**/api/engine/auth/logout", (r) => ((out++), r.fulfill({ json: { signed_out: true } })));
  await page.route("**/api/engine/setup", (r) => r.fulfill({ json: { needed: false } }));
  await page.route("**/api/engine/auth/mfa/enrol", (r) => r.fulfill({ json: { secret: "JBSWY3DPEHPK3PXP", otpauth_uri: "otpauth://totp/x" } }));
  await signedInAs(page, "admin", "mfa");
  await page.goto("/login/recovery");
  await expect(page.getByText("Lost your authenticator and your codes? Ask an admin to reset your MFA.")).toBeVisible();
  for (const [path, stage] of [["/login/mfa", "mfa"], ["/login/recovery", "mfa"], ["/mfa/enrol", "enrol"]] as const) {
    await signedInAs(page, "admin", stage);
    await page.goto(path);
    await page.getByRole("button", { name: "Sign in as someone else" }).click();
    await expect(page, path).toHaveURL(/\/login$/);
  }
  expect(out).toBe(3);
});

test("the MFA code accepts a pasted '123 456' and states the rule otherwise", async ({ page }) => {
  let sent: unknown = null;
  await page.route("**/api/engine/auth/login/mfa", (r) => ((sent = JSON.parse(r.request().postData() ?? "{}")), r.fulfill({ json: { stage: "full", user: user("admin") } })));
  await page.route("**/api/engine/runs", (r) => r.fulfill({ json: [] }));
  await page.route("**/api/engine/tas", (r) => r.fulfill({ json: [] }));
  await page.goto("/login/mfa");
  const code = page.getByLabel("6-digit code");
  await code.fill("12a");
  await page.getByRole("button", { name: "Verify" }).click();
  await expect(code).toHaveAttribute("aria-invalid", "true");
  await expect(code).toHaveAccessibleDescription(/Enter the 6 digits from your authenticator app\./);
  expect(sent).toBeNull();
  await code.fill("123 456");
  await page.getByRole("button", { name: "Verify" }).click();
  await expect.poll(() => sent).toEqual({ code: "123456" });
});

test("MFA set-up from account security asks for the password; forced enrolment does not", async ({ page }) => {
  const bodies: unknown[] = [];
  await page.route("**/api/engine/auth/mfa/enrol", (r) => {
    bodies.push(JSON.parse(r.request().postData() ?? "{}"));
    return r.fulfill({ json: { secret: "JBSWY3DPEHPK3PXP", otpauth_uri: "otpauth://totp/x" } });
  });
  await signedInAs(page, "viewer");
  await page.goto("/mfa/enrol?next=%2Fme%2Fsecurity");
  await expect(page.getByLabel("Setup key")).toHaveCount(0);
  await page.getByLabel("Current password", { exact: true }).fill("my password here");
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByLabel("Setup key")).toHaveText("JBSWY3DPEHPK3PXP");
  await expect(page.getByRole("button", { name: "Copy key" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Sign in as someone else" })).toHaveCount(0);
  await signedInAs(page, "admin", "enrol");
  await page.goto("/mfa/enrol");
  await expect(page.getByText("Admins need MFA. Set it up to continue.")).toBeVisible();
  await expect(page.getByLabel("Setup key")).toBeVisible();
  expect(bodies).toEqual([{ password: "my password here" }, {}]);
});

test("times are relative, with the absolute time and a named zone on hover and in the name", async ({ page }) => {
  const recent = new Date(Date.now() - 5 * 60_000).toISOString();
  await page.route("**/api/engine/auth/sessions", (r) =>
    r.fulfill({ json: [{ id: "00000000-0000-4000-8000-0000000000s1", created_at: recent, last_seen_at: recent, expires_at: recent, ip: "192.0.2.10", user_agent: "Firefox on Linux", current: true }] }),
  );
  await page.goto("/me/security");
  const t = page.getByRole("table", { name: "Active sessions" }).locator("time").first();
  await expect(t).toContainText("5 minutes ago");
  await expect(t).toHaveAttribute("title", /^\d{4}-\d{2}-\d{2} \d{2}:\d{2} \S+$/);
  await expect(t).toHaveAttribute("datetime", recent);
  expect(await t.locator(".sr-only").textContent()).toMatch(/^5 minutes ago, \d{4}-\d{2}-\d{2} \d{2}:\d{2} \S+$/);

  await page.route("**/api/engine/audit*", (r) => r.fulfill({ json: [{ id: 1, at: "2026-11-19 13:05:00+00:00", actor: "avery", user_id: null, event: "login", outcome: "success", ip: "192.0.2.10", detail: {} }] }));
  await page.goto("/settings/audit-log");
  await expect(page.getByRole("table", { name: "Audit log" }).locator("time")).toContainText(/2026-11-19 \d{2}:\d{2} \S+/); // absolute, zone named
});

test("setup: the command can be copied and errors sit under their field", async ({ page }) => {
  await page.route("**/api/engine/setup", (r) =>
    r.request().method() === "GET" ? r.fulfill({ json: { needed: true } }) : r.fulfill(envelope(403, "This setup token is not valid.")),
  );
  await page.goto("/setup");
  await expect(page.getByRole("button", { name: "Copy command" })).toBeVisible();
  await page.getByLabel("Setup token").fill("wrong");
  await page.getByLabel("User name").fill("avery");
  await page.getByLabel("Password", { exact: true }).fill("a long enough password");
  const again = page.getByRole("textbox", { name: "Password again" });
  await again.fill("something else entirely");
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(again).toHaveAttribute("aria-invalid", "true");
  await expect(again).toHaveAccessibleDescription(/The two passwords don't match/);
  await again.fill("a long enough password");
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByLabel("Setup token")).toHaveAttribute("aria-invalid", "true");
  await expect(page.getByLabel("Setup token")).toHaveAccessibleDescription(/This setup token is not valid\./);
  await expect(again).not.toHaveAttribute("aria-invalid", "true");
});

test("token: a failed copy says how to recover, expiry out of range is an inline error", async ({ page }) => {
  await page.route("**/api/engine/auth/tokens", (r) =>
    r.request().method() === "GET" ? r.fulfill({ json: [] }) : r.fulfill({ status: 201, json: { token: "pmxt_x", id: "00000000-0000-4000-8000-0000000000aa", name: "ci", role: "viewer", expires_at: "2026-12-19 10:00:00+00:00" } }),
  );
  await page.goto("/settings/api-tokens");
  await page.evaluate(() => Object.defineProperty(navigator, "clipboard", { value: { writeText: () => Promise.reject(new Error("denied")) } }));
  await page.getByRole("button", { name: "Create token" }).click();
  await page.getByLabel("Name").fill("ci");
  const days = page.getByLabel("Expires in (days)");
  await days.fill("120");
  await expect(days).toHaveAttribute("aria-invalid", "true");
  await expect(days).toHaveAccessibleDescription("Use 1 to 90 days.");
  await days.fill("10");
  await page.getByRole("dialog").getByRole("button", { name: "Create token" }).click();
  await page.getByRole("button", { name: "Copy" }).click();
  await expect(page.getByText("Copy failed. Select the token and copy it.")).toBeVisible();
});

test("users: own Disable explains why; Change role waits for a different role; confirm text is the description", async ({ page }) => {
  await page.route("**/api/engine/auth/users", (r) => r.fulfill({ json: [user("admin"), user("viewer")] }));
  await page.goto("/settings/users");
  const own = page.getByRole("button", { name: "Disable user… avery" });
  await expect(own).toHaveAttribute("aria-disabled", "true");
  await expect(own).toHaveAccessibleDescription("You can't disable your own account.");
  await own.click({ force: true });
  await expect(page.getByRole("alertdialog")).toHaveCount(0);

  await page.getByRole("button", { name: "Disable user… riley" }).click();
  await expect(page.getByRole("alertdialog")).toHaveAccessibleDescription("Signs them out everywhere. Their approvals and history stay.");
  await page.getByRole("button", { name: "Cancel" }).click();

  await page.getByRole("button", { name: "Change role… riley" }).click();
  const confirm = page.getByRole("button", { name: "Change role", exact: true });
  await expect(confirm).toBeDisabled();
  await page.getByRole("alertdialog").getByLabel("Role").selectOption("admin");
  await expect(confirm).toBeEnabled();
});

test("a viewer's empty runs list says an admin starts runs", async ({ page }) => {
  await signedInAs(page, "viewer");
  await page.route("**/api/engine/runs", (r) => r.fulfill({ json: [] }));
  await page.route("**/api/engine/tas", (r) => r.fulfill({ json: [] }));
  await page.goto("/");
  await expect(page.getByText("No runs yet. An admin starts runs.")).toBeVisible();
});
