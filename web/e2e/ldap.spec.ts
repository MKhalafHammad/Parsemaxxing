import type { Page, Request } from "@playwright/test";

import { expect, ldapCert as cert, ldapView as view, signedInAs, test, user } from "./fixtures";

/** Mock GET and PUT /auth/ldap; returns the PUT bodies. */
async function mockLdap(page: Page, v: object = view(), put?: (body: Record<string, unknown>) => { status: number; json: object }) {
  const puts: Record<string, unknown>[] = [];
  let gets = 0;
  await page.route("**/api/engine/auth/ldap", (r) => {
    if (r.request().method() === "GET") return (gets++, r.fulfill({ json: v }));
    const body = r.request().postDataJSON();
    puts.push(body);
    const res = put?.(body) ?? { status: 200, json: { ...v, version: 4, settings: { ...(v as { settings: object }).settings, ...body.settings } } };
    return r.fulfill(res);
  });
  return { puts, gets: () => gets };
}

test("save sends only changed fields with the version; servers reorder with Up and Down and ask for both passwords", async ({ page }) => {
  const { puts } = await mockLdap(page);
  await page.goto("/settings/authentication");
  await expect(page.getByRole("heading", { name: "Authentication and LDAP", level: 1 })).toBeVisible();
  await expect(page.getByRole("note")).toContainText("Local accounts always work when the directory is down. Local admins: 2.");
  await expect(page.getByRole("link", { name: "Show local users" })).toHaveAttribute("href", "/settings/users?source=local");

  await page.getByLabel("Bind DN").fill("cn=svc,dc=example,dc=com");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("status").filter({ hasText: "LDAP settings saved." })).toBeVisible();
  expect(puts[0]).toEqual({ expected_version: 3, settings: { bind_dn: "cn=svc,dc=example,dc=com" } });

  // A second server, moved to the top: now the bind password and the admin's password are required.
  await page.getByRole("button", { name: "Add server" }).click();
  await page.getByLabel("Server 2 URL").fill("ldap://ldap2.example.com:389");
  await page.getByLabel("StartTLS").nth(1).check();
  await page.getByRole("button", { name: "Move server 2 up" }).click();
  await expect(page.getByLabel("Server 1 URL")).toHaveValue("ldap://ldap2.example.com:389");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Fix these 2 settings" })).toBeVisible();
  expect(puts).toHaveLength(1);
  await expect(page.getByLabel("Your password (required)", { exact: true })).toHaveAttribute("aria-invalid", "true");
  await page.getByLabel("Bind password (required)", { exact: true }).fill("bind-secret-value");
  await page.getByLabel("Your password (required)", { exact: true }).fill("my-own-password");
  await page.getByRole("button", { name: "Save" }).click();
  await expect.poll(() => puts.length).toBe(2);
  expect(puts[1]).toEqual({
    expected_version: 4,
    settings: { servers: [{ url: "ldap://ldap2.example.com:389", start_tls: true }, { url: "ldaps://ldap1.example.com:636", start_tls: false }] },
    bind_password: "bind-secret-value",
    current_password: "my-own-password",
  });
  // Both typed passwords leave the page with the save.
  await expect(page.getByRole("status").filter({ hasText: "LDAP settings saved." })).toBeVisible();
  for (const v of ["bind-secret-value", "my-own-password"]) {
    expect(await page.locator(`input[value="${v}"]`).count()).toBe(0);
    expect(await page.content()).not.toContain(v);
  }
});

test("plain LDAP is shown as refused and is never sent", async ({ page }) => {
  const { puts } = await mockLdap(page);
  await page.goto("/settings/authentication");
  const url = page.getByLabel("Server 1 URL");
  await url.fill("ldap://ldap1.example.com");
  await expect(url).toHaveAttribute("aria-invalid", "true");
  await expect(url).toHaveAccessibleDescription("Plain LDAP is refused. Use ldaps:// or turn on StartTLS.");
  await page.getByLabel("Bind password (required)", { exact: true }).fill("x");
  await page.getByLabel("Your password (required)", { exact: true }).fill("y");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Fix this setting" })).toContainText("Servers 1: Plain LDAP is refused.");
  expect(puts).toHaveLength(0);
});

test("the bind password is write-only: Set, Change…, never prefilled", async ({ page }) => {
  const { puts } = await mockLdap(page);
  await page.goto("/settings/authentication");
  await expect(page.getByText("Set", { exact: true })).toBeVisible();
  await expect(page.locator("#ldap-bind_password")).toHaveCount(0); // no field until asked for
  await page.getByRole("button", { name: "Change…" }).click();
  const pw = page.getByLabel("New bind password", { exact: true });
  await expect(pw).toHaveValue("");
  await expect(pw).toHaveAttribute("type", "password");
  await pw.fill("new-bind-password");
  await page.getByRole("button", { name: "Save" }).click();
  await expect.poll(() => puts.length).toBe(1);
  expect(puts[0]).toEqual({ expected_version: 3, bind_password: "new-bind-password" });
  await expect(page.getByLabel("New bind password", { exact: true })).toHaveCount(0);
  expect(await page.content()).not.toContain("new-bind-password");

  await mockLdap(page, view({ bind_password_set: false }));
  await page.reload();
  await expect(page.getByText("Not set", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Set…" })).toBeVisible();
});

test("a version conflict offers Reload; a field error sits on its field", async ({ page }) => {
  const m = await mockLdap(page, view(), () => ({ status: 409, json: { error: { code: "conflict", message: "The LDAP settings changed meanwhile. Reload and try again.", request_id: "r1" } } }));
  await page.goto("/settings/authentication");
  await page.getByLabel("Bind DN").fill("cn=other,dc=example,dc=com");
  await page.getByRole("button", { name: "Save" }).click();
  const alert = page.getByRole("alert").filter({ hasText: "changed while you were editing" });
  await expect(alert).toBeVisible();
  const before = m.gets();
  await alert.getByRole("button", { name: "Reload" }).click();
  await expect.poll(() => m.gets()).toBe(before + 1);
  await expect(page.getByLabel("Bind DN")).toHaveValue("cn=parsemaxxing,ou=services,dc=example,dc=com");

  await mockLdap(page, view(), () => ({ status: 422, json: { error: { code: "invalid", message: "Invalid LDAP settings: user_filter: Value error, the filter must be one parenthesised LDAP filter", request_id: "r2" } } }));
  await page.reload();
  await page.getByLabel("User filter").fill("(uid={username})(x=1)"); // passes the UI's rough check; the engine refuses it
  await page.getByRole("button", { name: "Save" }).click();
  const filter = page.getByLabel("User filter");
  await expect(filter).toHaveAttribute("aria-invalid", "true");
  await expect(filter).toHaveAccessibleDescription(/the filter must be one parenthesised LDAP filter/);
});

test("the CA bundle uploads from a paste with both passwords and lists the parsed certificates", async ({ page }) => {
  await mockLdap(page, view({ ca_bundle: null }));
  let body: Record<string, unknown> = {};
  await page.route("**/api/engine/auth/ldap/ca-bundle", (r) => ((body = r.request().postDataJSON()), r.fulfill({ json: view({ ca_bundle: [cert("CN=Acme Issuing CA,O=Acme"), { ...cert(), sha256: "cd".repeat(32) }], version: 4 }) })));
  await page.goto("/settings/authentication");
  await expect(page.getByText("No CA bundle yet. Start here: upload the CA")).toBeVisible();
  const pem = "-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n";
  await page.getByLabel("CA bundle (PEM)").fill(pem);
  await page.getByRole("button", { name: "Upload CA bundle" }).click();
  await expect(page.getByLabel("Bind password for this upload (required)", { exact: true })).toHaveAttribute("aria-invalid", "true");
  expect(body).toEqual({});
  await page.getByLabel("Bind password for this upload (required)", { exact: true }).fill("bind-pw");
  await page.getByLabel("Your password for this upload (required)", { exact: true }).fill("own-pw");
  await page.getByRole("button", { name: "Upload CA bundle" }).click();
  await expect(page.getByRole("status").filter({ hasText: "CA bundle and bind password stored: 2 certificates. Directory users were signed out." })).toBeVisible();
  expect(body).toEqual({ pem, bind_password: "bind-pw", current_password: "own-pw", expected_version: 3 });
  const table = page.getByRole("table", { name: "CA certificates" });
  await expect(table).toContainText("CN=Acme Issuing CA,O=Acme");
  await expect(table).toContainText("cd".repeat(32));
  await expect(page.getByLabel("Bind password for this upload (required)", { exact: true })).toHaveValue("");

  // A wrong own password sits on its field; a stale version offers Reload.
  await page.route("**/api/engine/auth/ldap/ca-bundle", (r) => r.fulfill({ status: 403, json: { error: { code: "forbidden", message: "That password is not correct.", request_id: "r4" } } }));
  await page.getByLabel("Replace with a new bundle (PEM)").fill(pem);
  await page.getByLabel("Bind password for this upload (required)", { exact: true }).fill("bind-pw");
  await page.getByLabel("Your password for this upload (required)", { exact: true }).fill("wrong");
  await page.getByRole("button", { name: "Upload CA bundle" }).click();
  const own = page.getByLabel("Your password for this upload (required)", { exact: true });
  await expect(own).toHaveAttribute("aria-invalid", "true");
  await expect(own).toHaveAccessibleDescription(/That password is not correct\./);
  await page.route("**/api/engine/auth/ldap/ca-bundle", (r) => r.fulfill({ status: 409, json: { error: { code: "conflict", message: "The LDAP settings changed meanwhile. Reload and try again.", request_id: "r5" } } }));
  await page.getByRole("button", { name: "Upload CA bundle" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Reload, then upload again." }).getByRole("button", { name: "Reload" })).toBeVisible();
});

test("first-time setup says to upload the CA first; a wrong own password on save sits on its field", async ({ page }) => {
  await mockLdap(page, view({ ca_bundle: null, bind_password_set: false, missing_for_enable: ["servers", "ca_bundle", "bind_password"] }, { servers: [] }), () => ({
    status: 403,
    json: { error: { code: "forbidden", message: "That password is not correct.", request_id: "r6" } },
  }));
  await page.goto("/settings/authentication");
  await expect(page.getByText("No servers yet. First-time setup: upload the CA bundle with the bind password")).toBeVisible();
  await page.getByRole("button", { name: "Add server" }).click();
  await page.getByLabel("Server 1 URL").fill("ldaps://ldap1.example.com:636");
  await page.getByLabel("Bind password (required)", { exact: true }).fill("bind-pw");
  await page.getByLabel("Your password (required)", { exact: true }).fill("wrong");
  await page.getByRole("button", { name: "Save" }).click();
  const own = page.getByLabel("Your password (required)", { exact: true });
  await expect(own).toHaveAttribute("aria-invalid", "true");
  await expect(own).toHaveAccessibleDescription(/That password is not correct\./);
});

test("the directory session length is under Advanced and saved as a number", async ({ page }) => {
  const { puts } = await mockLdap(page);
  await page.goto("/settings/authentication");
  await page.getByText("Advanced").click();
  const hours = page.getByLabel("Directory session length (hours)");
  await expect(hours).toHaveValue("12");
  await expect(hours).toHaveAccessibleDescription(/Directory sessions end after this many hours so group changes take effect\./);
  await hours.fill("30");
  await expect(hours).toHaveAttribute("aria-invalid", "true");
  await hours.fill("8");
  await page.getByRole("button", { name: "Save" }).click();
  await expect.poll(() => puts.length).toBe(1);
  expect(puts[0]).toEqual({ expected_version: 3, settings: { session_max_hours: 8 } });
});

test("Test connection shows each step for each server", async ({ page }) => {
  await mockLdap(page);
  await page.route("**/api/engine/auth/ldap/test-connection", (r) =>
    r.fulfill({
      json: {
        ok: true,
        servers: [
          { url: "ldaps://ldap1.example.com:636", ok: false, steps: [{ step: "connect", ok: true, detail: "TCP connected" }, { step: "certificate", ok: false, detail: "certificate refused: hostname mismatch" }] },
          {
            url: "ldaps://ldap2.example.com:636",
            ok: true,
            steps: [
              { step: "connect", ok: true, detail: "TCP connected" },
              { step: "tls", ok: true, detail: "TLSv1.3" },
              { step: "certificate", ok: true, detail: "trusted", certificate_info: cert("CN=ldap2.example.com") },
              { step: "bind", ok: true, detail: "service bind succeeded" },
            ],
          },
        ],
      },
    }),
  );
  await page.goto("/settings/authentication");
  await page.getByRole("button", { name: "Test connection" }).click();
  const one = page.getByRole("group", { name: "Server 1 test" });
  await expect(one).toContainText("ldaps://ldap1.example.com:636");
  await expect(one).toContainText("Failed");
  await expect(one).toContainText("certificate refused: hostname mismatch");
  const two = page.getByRole("group", { name: "Server 2 test" });
  for (const t of ["Connect (TCP)", "TLS", "Certificate", "Bind", "service bind succeeded", "CN=ldap2.example.com"]) await expect(two).toContainText(t);
  await expect(two.getByText("Passed")).toHaveCount(5);

  await page.route("**/api/engine/auth/ldap/test-connection", (r) => r.fulfill({ status: 503, json: { error: { code: "unavailable", message: "The directory could not answer (timeout).", request_id: "r3" } } }));
  await page.getByRole("button", { name: "Test connection" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "The directory could not answer (timeout)." })).toBeVisible();
});

test("Test a user lookup shows DN, matched groups and role only", async ({ page }) => {
  await mockLdap(page);
  let body: unknown;
  await page.route("**/api/engine/auth/ldap/test-user-lookup", (r) =>
    ((body = r.request().postDataJSON()),
    r.fulfill({ json: { ok: true, found: 1, dn: "uid=jordan,ou=people,dc=example,dc=com", matched_groups: ["cn=pmx-admins,ou=groups,dc=example,dc=com"], role: "admin", message: "Found. This user signs in as admin." } })),
  );
  await page.goto("/settings/authentication");
  await page.getByLabel("User name to look up").fill("jordan");
  await page.getByRole("button", { name: "Test a user lookup" }).click();
  const result = page.getByRole("group", { name: "Lookup result" });
  await expect(result).toContainText("Can sign in");
  await expect(result).toContainText("uid=jordan,ou=people,dc=example,dc=com");
  await expect(result).toContainText("cn=pmx-admins,ou=groups,dc=example,dc=com");
  await expect(result).toContainText("Admin");
  expect(body).toEqual({ username: "jordan" });
  await expect(result).not.toContainText(/password/i);

  await page.route("**/api/engine/auth/ldap/test-user-lookup", (r) => r.fulfill({ json: { ok: false, found: 1, dn: "uid=kim,ou=people,dc=example,dc=com", matched_groups: [], role: null, message: "Found, but no group maps to a role: this user can't sign in." } }));
  await page.getByRole("button", { name: "Test a user lookup" }).click();
  await expect(result).toContainText("Can't sign in");
  await expect(result).toContainText("no group maps to a role");
  await expect(result).toContainText("No role");
});

test("Enable waits until nothing is missing, then saves enabled", async ({ page }) => {
  const { puts } = await mockLdap(page, view({ missing_for_enable: ["ca_bundle", "group_roles"], ca_bundle: null }));
  await page.goto("/settings/authentication");
  const toggle = page.getByLabel("Let directory users sign in");
  await expect(toggle).toHaveAttribute("aria-disabled", "true");
  await expect(toggle).toHaveAccessibleDescription(/Save these first: CA bundle Group to role mapping/);
  await toggle.click({ force: true });
  await expect(toggle).not.toBeChecked();
  await page.getByRole("button", { name: "Save" }).click();
  expect(puts).toHaveLength(0);

  const ready = await mockLdap(page);
  await page.reload();
  await page.getByLabel("Let directory users sign in").check();
  await page.getByRole("button", { name: "Save" }).click();
  await expect.poll(() => ready.puts.length).toBe(1);
  expect(ready.puts[0]).toEqual({ expected_version: 3, settings: { enabled: true } });
});

test("a viewer sees the page admin-only and the settings are never requested", async ({ page }) => {
  await signedInAs(page, "viewer");
  const seen: Request[] = [];
  await page.route("**/api/engine/auth/ldap**", (r) => (seen.push(r.request()), r.fulfill({ status: 403, json: {} })));
  await page.goto("/settings/authentication");
  await expect(page.getByText("Only admins can see the directory settings.")).toBeVisible();
  await expect(page.getByRole("note")).toContainText("Local accounts always work when the directory is down.");
  for (const name of ["Save", "Test connection"]) await expect(page.getByRole("button", { name })).toHaveAccessibleDescription("Admin only");
  expect(seen).toHaveLength(0);
});

test("directory users: a Directory badge, role from groups, no token creation", async ({ page }) => {
  await page.route("**/api/engine/auth/users", (r) => r.fulfill({ json: [user("admin"), user("viewer", { id: "00000000-0000-4000-8000-000000000003", username: "jordan", source: "ldap" })] }));
  await page.goto("/settings/users?source=ldap");
  const table = page.getByRole("table", { name: "Users" });
  await expect(table.getByText("Directory", { exact: true })).toBeVisible();
  await expect(table.getByText("avery")).toHaveCount(0); // filtered to directory users from the URL
  const role = page.getByRole("button", { name: "Change role… jordan" });
  await expect(role).toHaveAttribute("aria-disabled", "true");
  await expect(role).toHaveAccessibleDescription("Role comes from directory groups.");
  await role.click({ force: true });
  await expect(page.getByRole("alertdialog")).toHaveCount(0);

  await page.route("**/api/engine/auth/me", (r) => r.fulfill({ json: { user: user("viewer", { source: "ldap" }), stage: "full", via: "session", mfa_required: true } }));
  await page.route("**/api/engine/auth/tokens", (r) => r.fulfill({ json: [] }));
  await page.goto("/settings/api-tokens");
  const create = page.getByRole("button", { name: "Create token" });
  await expect(create).toHaveAccessibleDescription(/Directory accounts can't create API tokens/);
  await create.click({ force: true });
  await expect(page.getByRole("dialog")).toHaveCount(0);
});
