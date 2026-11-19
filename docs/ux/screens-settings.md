# Settings screens

Status: **planned**. Settings holds **platform-level** settings only; environment and customer settings live on the environment's page ([screens-environments.md](screens-environments.md)). Every setting uses the [setting row pattern](screens-environments.md#setting-row-inherited-and-overridden) with its source ("Default", "Set at platform level", "Managed by environment variable").

Layout: a secondary navigation list on the left of the Settings area, in this order: General · LLM providers and agents · Budgets · Authentication and LDAP · Users · API tokens · Data policies · Security health · Audit log · About. The page title carries "Platform setting: applies to every environment" under it.

Common to all Settings pages:
- Viewers see every page read-only; secret fields show "Set, updated <date>" or "Not set"; every action is disabled with "Admin only".
- Save is per section (not one global save), with an unsaved-changes notice and "Discard changes".
- Every change is recorded in settings history; the page footer links "History of this page".
- New runs read a settings snapshot at start; the save confirmation says "Running runs keep the settings they started with."

## General (Phase 15)

- Public URL and allowed origins (read-only, "Managed by environment variable" since they are bootstrap); default theme; session idle and absolute timeouts (30 minutes, 12 hours); "mask raw samples for viewers" (off by default); optional `pmx_audit` forwarding (Phase 19): target environment and index; settings export and import (non-secret JSON, diff before apply); `.env` keys that can be removed after the v1 import (list, from 7.5).
- **Acceptance:** import shows a diff and applies nothing until "Apply changes"; a bootstrap setting has no input.

## LLM providers and agents (Phase 16)

- **Providers table:** name, kind, preset, model, hosted or on-prem (icon plus word), last probe result (structured-output mode, latency), concurrency, price per million tokens, used by (agents). Primary action: Add provider.
- **Add or edit provider:** preset picker fills the base URL; API key (write-only); model; Azure deployment name; hosted or on-prem; timeout, concurrency, context window, max output tokens, prices under Advanced. **Test** runs the capability probe and must pass before the provider can be assigned; result shows each mode tried.
- **Agents table:** Profiler, Index-time, Extraction, CIM mapper, Router, Drift Analyst (with their actor identity), primary model, fallback (optional, "used only on infrastructure errors, never to retry bad output"), customers whose data policy blocks this provider (warning).
- **Kill switch:** "Stop all model calls…" (destructive, confirmed), and its state banner.
- **Acceptance:** an untested provider can't be selected in the agents table; a hosted provider assigned while a customer forbids hosted models shows that customer's name in a warning.

## Budgets (Phase 16)

- Per-run token and cost caps, daily cap across providers, per-provider concurrency, current use today with a meter (value and text), budget hits this week (link to Analytics).

## Authentication and LDAP (Phases 13, 14)

- Local accounts: password rules (shown, not editable below the minimums), lockout policy (shown), "Require MFA for admins" (on by default), "Allow TOTP for LDAP users".
- LDAP: [flows.md F11](flows.md#f11-ldap-setup-phase-14). Servers (ordered list with up and down buttons, not drag), CA bundle, bind DN, bind password (write-only), search settings, membership mode, group to role mapping table, Advanced (timeouts, page size), Test connection, Test a user lookup.
- Break-glass note, always visible: "Local accounts always work when the directory is down. Local admins: 2." with a link to Users filtered by local.
- **Acceptance:** plain LDAP (`ldap://` without StartTLS) is not offered; Test a user lookup shows DN, matched groups and role only.
- Decision, Phase 14: built at `/settings/authentication`. The bind password field is required when the servers change, with "Your password" beside it; the CA bundle upload also asks for both. "Require MFA for directory users" and "Directory session length" are on this screen. Viewers see "Only admins can see the directory settings." in place of the form. The rules in [flows.md F2 and F11](flows.md#f11-ldap-setup-phase-14) apply (no "directory down" banner on sign-in; owner to confirm).

## Users (Phase 15)

- **Table:** name, user name, source (Local or LDAP), role, MFA (enrolled or not), last sign-in, status (Active, Locked, Disabled). Filters by source and role.
- **Primary action:** Add user (local): name, user name, role, temporary password or invite link (shown once), "Require MFA at first sign-in".
- **Row actions (admin):** Change role… (signs the user out everywhere, said in the dialog), Reset MFA…, Unlock, Disable user…, Sign out everywhere. LDAP users: role comes from groups, shown read-only with the group name.
- **Viewer (exception to "every page read-only"):** the engine lists users to admins only (Phase 13), so viewers see Add user disabled with "Admin only" and, in place of the table, "Only admins can see the user list. Ask an admin to add or change a user." Owner may overrule.
- **Acceptance:** an admin can't remove their own admin role if they are the last local admin ("Keep at least one local admin for break-glass access").

## API tokens (Phase 13 back end, Phase 15 screen)

- **Table:** name, owner, role, created, expires (days left; warning at 14 and 3 days), last used, status. Admins see everyone's tokens and can revoke any; everyone sees their own (from the user menu, pre-filtered "Mine").
- **Primary action:** Create token ([flows.md F12](flows.md#f12-api-token-creation-phase-13-back-end-phase-15-screen)): name, role no higher than your own, expiry 1 to 90 days (required). The value is shown once.
- **Acceptance:** after closing the created dialog the token value is not in the DOM or any later API response; expiry over 90 days is refused inline.

## Data policies (Phase 15 page; retention Phase 21; egress Phase 16)

- Platform defaults and a table per customer: hosted models allowed, real-data retention (0 to 30 days, default 30), approved add-ons as knowledge examples (on by default), fix memory across customers. Each row shows effective value and source; per-environment overrides are on the environment's Data policy tab, linked from each row ("Overridden in 1 environment").
- Copy under retention: "Real logs are deleted this many days after a run ends. Nothing is kept longer than 30 days."

## Security health (Phase 15; rows added by later phases)

- **Purpose:** one list of every insecure toggle that is on and every integrity check result (A02, A08).
- **Content:** configuration checks (TLS verify off anywhere, MFA not required, OpenAPI docs exposed, debug on, HTTPS profile off on a non-localhost URL), ledger integrity (last `ledger verify` result and time, "Verify now"), package store integrity (last check, failures listed with the version), KEK backup reminder, tokens and keys expiring, audit forwarding status.
- Each row: result word and icon, why it matters (one line), how to fix (link).
- **Acceptance:** with a fixture where an environment has TLS verify off, a Warning row names that environment and links to its Connection tab.

## Audit log (Phase 15)

- **Table:** time, actor (user or token name), action, object (with customer and environment), client IP, outcome. Filters: actor, action type (login, settings, secret, approval, deployment, download, raw-sample view), customer, environment, outcome, date. Export as CSV or JSON.
- Read-only for everyone ("Nobody can edit the audit log"); the ledger integrity badge (from Security health) is shown in the header.
- **Acceptance:** viewing raw samples of a production customer creates a row visible here; there are no edit or delete controls.

## About (Phase 15)

- Version, licence (PolyForm Shield 1.0.0, link to LICENSE), third-party notices (including the pinned `splunk/splunk-agent-skills` commit and licence), supported Splunk Enterprise versions (10.2 and later) and the CIM compatibility table (from `environments/versions.py`), the principle line "Agents propose · code acts · Splunk judges · you approve", a link to docs. No author or tool attribution beyond the repository owner.
