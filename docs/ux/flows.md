# User flows

Status: **planned**. Each flow names the phase that builds it. Words follow [copy.md](copy.md); screens are specified in [screens.md](screens.md), [screens-environments.md](screens-environments.md) and [screens-settings.md](screens-settings.md).

Example data used throughout: vendor Acme (add-on `TA-parsemaxxing-acme-fw`), customers Globex and Initech, environments `globex-prod` (dedicated, SHC plus two HFs, one of them an HF-DS), `msp-shared-1` (shared, Globex and Initech), sandbox `sbx-10-6`, hosts under `example.com`, addresses from 192.0.2.0/24.

Every flow obeys:
- Long tasks show progress, can be left, and are resumable from "Needs you" or the object's page.
- Every production action is confirmed in a dialog that names the customer, the environment and the package SHA-256 ([copy.md](copy.md#confirmation-dialogs)).
- Viewers can follow every flow up to the first admin action, which they see disabled with "Admin only".
- Every step is keyboard reachable in document order; focus moves to the new step's heading on step change.

## F1. First-run setup (Phase 15; setup token in Phase 13)

| # | Step | User does | System does |
| --- | --- | --- | --- |
| 1 | Open the app | Goes to the public URL | No admin exists: every route redirects to `/setup`. The page explains: "Parsemaxxing has no admin yet. Enter the setup token from the engine's data volume." It shows the file path the engine logged and a copyable command to read it (the exact command is fixed in Phase 13 and documented in `docs/setup.md`). |
| 2 | Setup token | Pastes the token (paste allowed) | Checks it (single use, 60 minutes). Wrong or expired: "This setup token is not valid. Tokens expire 60 minutes after the engine starts; restart the engine to get a new one." |
| 3 | First admin | User name, display name, password twice (12 to 128 characters; a strength meter that states the rule, not composition rules) | Common-password check inline: "This password is on the list of common passwords. Pick another." |
| 4 | MFA (required by default for local admins) | Scans the QR code or copies the key, enters a 6-digit code | Shows 10 recovery codes once, with Download and Copy; "I have saved these codes" checkbox enables Continue |
| 5 | LLM provider | Picks a preset (Meta Model API, OpenAI, Azure OpenAI, Anthropic, Google Gemini, Mistral, vLLM, Ollama, LM Studio), enters key and model, presses Test | Runs the capability probe; shows mode found, latency, tokens. Must pass to continue. "Skip for now" is allowed but leaves the checklist item open and blocks runs. |
| 6 | Sandbox Splunk | `local-sandbox` is pre-filled from the v1 migration or the bundled stack; admin confirms URL and token, presses Test | Connection test plus version (10.2 or later) and CIM add-on check. CIM missing: link to CIM library upload, not blocking setup. |
| 7 | First production environment (optional) | "Add one now" opens the add-environment wizard (F3) inside setup; "Later" skips | |
| 8 | Done | Lands on Overview | Overview shows the setup checklist (provider tested, sandbox tested, CIM library has the sandbox's version, first production environment, LDAP or more users, `.env` keys that can now be removed) until every item is done or dismissed |

Decision points: skip LLM provider (allowed, blocks runs); skip production environment (allowed). Resumable: closing the browser after step 3 resumes at the first incomplete step after sign-in.
What can go wrong: two people open `/setup` at once (the second sees "Setup is already complete" once the first admin exists); token file missing (explain where it is written and how to restart the engine).
Acceptance (Phase 15): a new admin completes F1 without docs; the walkthrough is recorded in `docs/ux/reviews/phase-15.md`.

## F2. Sign in, MFA and recovery (Phase 13)

1. `/login`: user name, password, "Sign in". Local and LDAP accounts use the same form; the engine decides. Password managers and paste work (WCAG 3.3.8).
2. If MFA is enrolled: `/login/mfa` with one 6-digit field (`autocomplete="one-time-code"`, numeric keyboard), "Use a recovery code instead" link.
3. If MFA is required but not enrolled: forced `/mfa/enrol` before any other page.
4. Success returns to `next` (validated same-origin path) or Overview.

What can go wrong and what the user sees:
- Any failure: one message, "Sign-in failed. Check your user name and password." (no enumeration).
- Lockout with backoff: "Too many attempts. Try again in 2 minutes." The countdown is text, updated each minute, not a live timer announced every second.
- LDAP down: same generic message for LDAP users; the login page shows "Directory sign-in is unavailable. Local accounts still work." only when the engine reports the directory down.
- Recovery code used: after sign-in a banner says "You used a recovery code. 9 are left. [Create new codes]".
- Idle timeout: 2 minutes before, a non-modal banner "You will be signed out in 2 minutes. [Stay signed in]"; after, `/login?next=` with "Your session ended."

## F3. Connect an environment (Phase 17)

Screens: [screens-environments.md](screens-environments.md#add-environment-wizard). Steps:

| # | Step | Decision | What can go wrong (shown inline, with the fix) |
| --- | --- | --- | --- |
| 1 | Type and customer | Dedicated (pick or create a customer) or Shared (MSSP); name (`^[a-z0-9-]{2,32}$`), colour | Name taken: "globex-prod already exists. Pick another name." |
| 2 | Entry point | Connected (URL plus read token) or Handoff only (no network path, enter details by hand, see F13) | |
| 3 | Entry search head | URL `https://sh1.globex.example.com:8089`, `parsemaxxing_read` token, CA bundle, verify TLS (on, cannot be turned off without a typed reason under Advanced) | DNS, TCP, TLS or auth failure with the specific cause; token lacks capabilities: lists the missing ones and offers "Show the Splunk role script" |
| 4 | Auto-discover | Code reads server info, roles, cluster and SHC status; shows a progress list per call | Partial discovery: what was found plus "Couldn't read cluster status: the token can't read `cluster/master/info`. Add nodes by hand or extend the role." |
| 5 | Confirm nodes | Each proposed node is a row with checkboxes per role (multi-role allowed), "Include" toggle, and the reason it was proposed; for a DS, "Serves: universal forwarders / heavy forwarders / both"; "Add node" by hand | Nothing is added without a tick. An HF that is also a DS for universal forwarders is shown as "HF-DS" once both roles are ticked. A node below 10.2 shows "Not supported" and can't be included. |
| 6 | Clients and indexes (shared only) | Index naming convention with `<client>` placeholder (default `cus_<client>_*`); per customer: derived allowlist (editable exceptions), its HFs, its HF-DS, optional DS for HFs | Every HF and DS must belong to exactly one customer: unassigned ones block Continue with "Assign hf3.example.com to a customer." |
| 7 | Sandbox and CIM | Link a sandbox; installed CIM version read (or entered); matching library upload shown | Version mismatch major.minor: warning, with "Make this blocking" toggle. No matching CIM upload: warning "CIM work will be blocked until you upload Splunk_SA_CIM 8.5.1". |
| 8 | Delivery | Handoff (default) or Managed; for managed, per deployer and DS for HFs: "Set up relay" (can be done later from Connection) | |
| 9 | Run all tests | One button; per node per row of the connection table: DNS, TCP, TLS, auth, capabilities, version, role, token expiry, relay status | Any failure keeps the environment a Draft, with each failure's fix |
| 10 | Done | Environment becomes active; lands on its Overview tab | |

Draft: every step saves on Continue; the environment is listed as "Draft" and the wizard resumes at the first incomplete step. Nothing in a draft is used by runs, discovery or deployments. "Discard draft" deletes it and its credentials.

## F4. Run a build (v1, rehomed in Phase 15; target environment in Phase 17)

1. Runs → New run (side sheet, kept from v1). Fields: log file, "Update an existing add-on" (else new), vendor, product, time zone, optional **target environment** (Phase 17: "Build for: globex-prod" picks its linked sandbox, Splunk and CIM version; default "No target: use sbx-10-6"), optional customer (needed for data policy and retention), "Skip profile review" (kept).
2. Before start the sheet shows: sandbox to be used, Splunk and CIM version, estimated tokens and cost, which providers the customer's data policy allows, and when real data is deleted ("30 days after the run ends").
3. Start run: the sheet closes, a status message names the run ID, the run appears on the board, and the workspace opens on demand.
4. The run workspace shows the phase rail, the Now banner, attempts, gate verdicts, checks and the activity feed live (kept from v1).
5. If profile review is on: F5. Then stages run. Then approval: F6.

What can go wrong: data policy blocks the run (egress error from [copy.md](copy.md#error-pattern), shown before Start run is enabled); CIM version missing for the target (start allowed, the CIM stage is marked "Blocked: upload Splunk_SA_CIM 8.5.1" and the run ends as a parsing-only add-on, said before start); sandbox failing (start disabled with the environment link); budget or kill switch (the run pauses with a banner naming the cap and who can raise it).

## F5. Profile review with the format check (v1, extended in Phase 17c)

1. "Needs you" → Review profile. The workspace opens on the Profile review phase.
2. The Profiler's findings with field coverage meters (kept). New in 17c, at the top: **Format check**: "Code detected: syslog with an embedded CEF payload. Profiler says: syslog with CEF payload. They agree." When they disagree: a warning card, "Code detected CEF; the Profiler says key=value. Pick the format Splunk should use:" with both options as radio buttons, each with the evidence (signature lines matched, 3 example lines as escaped text).
3. Time source (syslog with payload): "Event time comes from: the syslog header / the payload's own time", Profiler's choice preselected with its reason.
4. Encoding, header lines (CSV, W3C), payload format, time zone when the raw timestamp has no offset (kept).
5. Corrections are marked "You changed this" (kept). Confirm profile.

What can go wrong: disagreement left unresolved (Confirm disabled, the card says why); header lines that look like events (shown with a "Header line, never counted" tag).

## F6. Approval, including the data model decision (v1, extended in 17c and 18)

1. "Needs you" → Review and decide. The approval report opens (kept: summary, CIM meters, attempts per phase, holdout, how it was validated, raw vs parsed, configuration view, update row diff and `local/` overrides).
2. **Decisions the agents made → Data model** (17c), in this order:
   - Plain summary: "The CIM mapper mapped `action=allow|deny` events to Network_Traffic (All_Traffic) and `type=ips` events to Intrusion_Detection. It rejected Web and Network_Sessions."
   - Per event category: chosen model and dataset, fit score bar with the number ("9 of 10 required fields filled"), the Splunk CIM check result next to it.
   - Field-level plan (table, expandable): CIM field, source field, values that prove it (`dest_port` ← `dstport`: 443, 53, 22), coverage; "Not in the source" rows; enum mappings (`deny`, `drop` → `blocked`) with counts and any unmapped value ("`reset` (12 events) is not mapped").
   - Rejected alternatives: each with its fit score and the reason in one line.
   - Flags from code bounds: "The choice cites fields the fit score could not see", "Selection was re-run once after the CIM checks".
   - "No CIM model fits" shows the reason and "This add-on is built without CIM mapping."
3. References used (Phase 20): chunk title, tier, version, page; tier 7 marked "example from <add-on>, not verified".
4. Production preview (Phase 18, optional, second option): shown next to the sandbox result, labelled "Preview on production (read-only, extra)". Never replaces the sandbox result.
5. Decision bar (kept, sticky): SHA-256, Download package, Reject…, Approve version…. The approve dialog says the version is registered and not deployed anywhere (D7).
6. After approval: "Version 1.3.0 registered. [Deploy to an environment] [Open add-on]".

What can go wrong: the hash isn't loaded (Approve disabled, as in v1); a correction to the model choice is a planned report-correction feature, shown as "Send back to CIM stage" only once it is built.

## F7. Deploy: plan, impact, approve, deliver, verify, roll back (Phase 18)

| # | Step | Admin sees and does |
| --- | --- | --- |
| 1 | Start | From a version ("Deploy this version…"), an add-on, a run's success message, or Deployments → New deployment. The dialog starts from the customer: lists Globex's dedicated environments and every shared environment where Globex has indexes, each with current version per tier and health. Tick one or more. |
| 2 | Plan created | One deployment per ticked environment. Each opens as its own page, status Planned. The plan lists every node: included or left out, tier, how it gets the package (directly, through deployer, through DS for HFs), and why ("hf-ds1: HF-DS, not a client of a DS for HFs: installed directly"; "idx1: indexer, never a deployment target"; "ds-uf1: serves universal forwarders: never used"). |
| 3 | Compatibility and impact | Running checks with progress: Splunk version and spec keys for the target version, CIM definitions of the target, existing apps and sourcetype stanzas with the same names, `local/` overrides, restart needed, customers and indexes receiving the sourcetype, the shared search head check (shared only), the negative routing test (routing add-ons). Each check: result word, evidence one click away. |
| 4 | Request approval | "Request approval". Blocking results disable it with the reason. Four-eyes environments say "Another admin must approve." |
| 5 | Approve | "Approve deployment…" dialog ([copy.md](copy.md#confirmation-dialogs)): customer, environment colour and name, tiers in order, restart, SHA-256; typed environment name when high risk. |
| 6 | Deliver | Managed: tier by tier (HFs first, then search heads), each tier with progress and the live relay console (read-only). Handoff: the runbook with copy buttons, "Copy all as a script", "Download bundle" (`.tgz`, `SHA256SUMS`, runbook), then "Mark delivered…". |
| 7 | Verify | Per tier: installed version and hash, effective settings read back, smoke search on new events (waits for data with a visible "Waiting for new events of acme:fw (0 so far, checks every minute)", can be left). Handoff-only offline environments: "Verification skipped: globex-offline has no connection. Confirm manually." with a checklist. |
| 8 | Result | Deployed: the add-on page's "where it runs" table updates. Failed: status names the step and tier, rollout stopped; "Roll back…" offers to restore the tiers already done to what they ran before. Nothing is retried silently. |

Decision points: several environments (each deployment independent); shared search head check blocks a customer (the plan offers a customer-specific sourcetype name and links the onboarding note); version mismatch (warning or blocking per environment setting); deprecated version (typed confirmation).
Rollback: creates a new deployment of the previous version per tier, same pipeline and approval. Version 1.3.0 stays registered.
Viewer: sees plans, impact, console, results; every button disabled with "Admin only".

## F8. Add-on versions: find, view, compare, download, revert, roll forward (Phase 17b; per production environment once Phase 18 lands)

Goal check: answer "what changed between 1.2.0 and 1.4.0, and what runs in production now?" in under a minute.

1. **Find**: Add-ons list, or global search "acme-fw 1.2". The list shows each add-on's latest version and a compact "where it runs" summary ("globex-prod 1.4.0 · msp-shared-1 search heads 1.3.0, Initech HFs 1.3.0").
2. **Add-on page**: version timeline (newest first, with Latest, Deprecated, Integrity failed badges, who approved, from which run) and a lineage tree toggle (parent links; a revert then update shows a branch). Above it, the **Where it runs** table: environments grouped by customer, rows per tier, the version on each, "Newer version available" when behind.
3. **View files**: a version's Files tab: tree (only allowlisted files), `.conf` in the editor-style pane with "Explain settings", CSV lookups as a table, size cap message for big files ("Showing the first 2,000 lines of 9,100. [Download package]").
4. **Compare any two**: "Compare versions" opens two pickers (from, to; any pair, either order) defaulting to the previous and the selected version; "Swap". Summary first: "3 files changed, 1 added. props.conf: 2 stanzas changed, 4 settings added." Then per file the setting-level diff as rows, then the side-by-side text. Deep link copies the URL.
5. **Compare with installed**: pick an environment (and tier for split environments); shows version vs effective settings read back, `local/` overrides flagged "Set in local/ on the target, not from this add-on".
6. **Download**: promoted `.tgz` plus `SHA256SUMS`; "Tested package" under "More". The hash is shown in full before download. Audited; viewers can download.
7. **Revert**: version page → "Deploy this version…" (for older versions the label is "Revert an environment to this version…"). The dialog picks customer and environment, then shows: current version on each tier, target version, and in a highlighted line "**Newer versions are kept.** 1.3.0 and 1.4.0 stay in the registry and can be deployed again at any time." Plus "Index-time changes affect only data indexed after the revert." It creates a deployment (F7). If the revert removes a routing transform, the plan states the negative routing test re-runs.
8. **Roll forward**: on the add-on page, after a revert, the environment row shows "Runs 1.2.0 · Newer version available: 1.4.0 [Deploy 1.4.0…]". The timeline marks reverts and roll forwards as events between versions.

What can go wrong: integrity failed (version page shows the error, download and deploy disabled, Security health link); file too large; compare with installed on a handoff-only environment ("No connection: compare with installed needs the read API").

## F9. Discovery to run (Phase 21; overlay in 21b)

1. Discovery → "Scan index…": pick customer (shared), environment, index (only the customer's allowlisted indexes are offered), optionally a sourcetype. Manually triggered only.
2. Progress per check group (volume, sample, index-time health, search-time health, CIM health, ownership, name quality, mixed feed), leavable.
3. Results: one finding per (index, sourcetype), sorted by severity, with verdict word, health score and the evidence numbers. Discovery stores counts and verdicts only, said in the page description.
4. Finding page: plain summary ("Timestamps fall back to index time on 38% of events; parser warnings: DateParserVerbose 1,204 in 24 h") → evidence → "Start a run from this finding". The run sheet opens pre-filled (samples pulled, environment, current sourcetype); masking note: "The model sees masked samples; the sandbox tests the real ones."
5. Owned by another add-on: "Start an overlay fix" (21b) instead; names the owning add-on and what is wrong.
6. Samples unusable: the finding asks for the raw file and opens the run sheet with the file field focused.

What can go wrong: index outside the allowlist (refused before any search, tenant isolation error); read token can't search `_internal` (the index-time checks show "Not checked: the read role can't search _internal" and the rest proceed).

## F10. Drift to deployment (Phase 22)

1. A drift signal arrives (webhook per environment). "Needs you" shows "Drift on globex-prod: acme:fw".
2. Drift page: signal, Drift Analyst verdict (real change or not, with evidence), the masked samples it fetched.
3. Real change: an update run starts (or "Start update run" if the environment is set to ask first). It follows F4 to F6.
4. After approval, a deployment to **globex-prod only** is proposed (status Planned, "Proposed by drift"), never delivered without F7's approval. Other environments running the add-on show "Newer version available".
5. Not real: "Dismissed by the Drift Analyst" with the reason; an admin can reopen.

## F11. LDAP setup (Phase 14)

1. Settings → Authentication and LDAP → "Set up LDAP". Shows first: "Local accounts keep working when the directory is down. Your local admin accounts: Avery (you)."
2. Servers (ordered, LDAPS 636 or StartTLS only; plain LDAP isn't offered), CA bundle upload, hostname check (always on).
3. Bind DN and password (write-only), user search base, filter template, username attribute (select), group search base, membership mode (select with a one-line explanation of each, including AD nested groups), timeouts, page size under Advanced.
4. Group to role mapping table: group DN → Viewer or Admin; a note "No mapped group means no access."
5. "Test connection" shows each step (TCP, TLS, certificate, bind) with pass or fail. "Test a user lookup" with a user name: found DN, groups matched, resulting role; never other attributes, never the password.
6. Save. "Optional: let LDAP users enrol TOTP in Parsemaxxing" toggle.

What can go wrong: certificate mismatch, bind failure (specific in the test, generic on the login page), more than one entry for the filter ("The filter matched 2 entries. Make it match exactly one."), user in no mapped group ("Found, but no group maps to a role: this user can't sign in.").

## F12. API token creation (Phase 13 back end, Phase 15 screen)

1. User menu → API tokens, or Settings → API tokens.
2. Create token: name (required, for example `ci-runner`), role (no higher than your own; a viewer sees Viewer only), expiry (required, 1 to 90 days, default 30, date shown).
3. Created: the token `pmxt_…` is shown **once**, monospace, with Copy, and "You won't see this token again. Store it in your secret manager." Done closes; the list shows name, role, created, expires (days left), last used, Revoke.
4. CLI hint under the token: `export PMX_TOKEN=<your token>` (placeholder, never the real value).

What can go wrong: expiry above 90 days (inline rule); closing the dialog before copying (confirm "Close without copying? The token can't be shown again.").

## F13. Bring an offline environment in (Phase 17 environment, 17c specs and CIM, 20 knowledge pack)

1. Add environment → "Handoff only (no network path)". The wizard asks for topology by hand: nodes with roles, Splunk version per node, installed CIM version. It says: "Connection tests, impact searches and post-deploy verification are skipped for this environment."
2. **Spec bundle**: CIM and versions tab → "Upload spec bundle". Shows the exact command to run on any node: `tar czf specs.tgz -C $SPLUNK_HOME/etc system/README system/default/props.conf splunk.version` with Copy. After upload: version read from `splunk.version` and checked against the environment's version; mismatch shown before saving.
3. **CIM definitions**: Environments → CIM library → upload `Splunk_SA_CIM` of the same version (downloaded from Splunkbase by the team); or, if the environment has local data model changes, upload its definitions on the CIM and versions tab.
4. **Knowledge pack** (Phase 20): Knowledge → Import → "Import a signed pack": signature checked against a registered public key, every file hash checked, then quarantine; an admin approves.
5. Deploy works in handoff mode only; verification becomes a manual checklist.

What can go wrong: unsigned or tampered pack (refused, names the first bad file); spec bundle for an unsupported version (refused, D10); CIM version outside the compatibility table (refused with the reason).

## F14. Second environment, isolated (Phase 17)

The walkthrough that proves the isolation requirement lives in [screens-environments.md](screens-environments.md#isolation-walkthrough).
