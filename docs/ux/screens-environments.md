# Environment screens

Status: **planned**, Phase 17 (CIM library and spec bundle in 17c, Deployment tab targets and relay in 18, Discovery and drift tab in 21 and 22, retention in 21). Source: master prompt 7.1, 7.2, 7.5, 7.13, 7.16, D1 to D3, D10, D11.

Owner requirement: **configuring each Splunk environment is easy and clearly isolated.** Everything here is designed so that an admin always knows which environment and customer they are editing, and never sees another environment's values while doing it.

## Isolation rules the UI enforces

| Rule | How the screen shows it |
| --- | --- |
| One environment per page | Every environment route is `/environments/<env>/<tab>`. The page loads only that environment's data. No tab has an environment picker; switching environment means leaving the page. |
| Identity always visible | The page header has the environment's colour band, name, kind badge (Production or Sandbox, icon plus word), model badge (Dedicated or Shared (MSSP)), customer(s) and health. It stays visible (sticky) on every tab. |
| No cross-environment values | Credential and CA pickers list only this environment's items (and, on a shared environment, only the chosen customer's when scoped to one). A secret can't be selected from another environment, and the UI never offers to. |
| Copy is explicit | "New environment from this one" copies non-secret settings into a draft and says what it did not copy: "Nodes, credentials, relay keys and CA bundles are never copied. Enter and test them for the new environment." |
| Tests are scoped | Each "Test" button names its target: "Test sh1.globex.example.com". "Run all tests" names the environment. A test never touches another environment. |
| History is scoped | The History tab shows only this environment's changes (and its customers' overrides on a shared environment). |
| Effective value and source | Every setting row shows its value and where it comes from, with "Reset to inherited" next to every override ([pattern below](#setting-row-inherited-and-overridden)). |

## Environments section layout

`/environments` has three tabs: **Environments** · **Customers** · **CIM library**.

### Environments list

- **Purpose:** see every Splunk Parsemaxxing knows and which needs attention.
- **Primary action:** Add environment (admin).
- **Content:** a card per environment, grouped by customer (shared environments in their own group "Shared (MSSP)", sandboxes last), sorted by attention first. Each card:

```
+----------------------------------------------------------------+
| ## (colour) globex-prod                 [x] Failing            |
| Globex · Production · Dedicated                                |
| Splunk 10.6.1 · CIM 8.5.1 · Managed delivery                   |
| Sandbox: sbx-10-6                                              |
| ! sh2.globex.example.com: TLS certificate not trusted          |
| ! Read token expires in 6 days                                 |
|                                 [Open]  [Test connection]      |
+----------------------------------------------------------------+
```

  Needing attention: failed connection test, token or key expiring (14 and 3 days), CIM version not uploaded, sandbox CIM mismatch, Splunk version unsupported, version mismatch with sandbox, draft not finished. Up to 2 lines, "+3 more" link to the Overview tab.
- **Filters:** customer, kind, model, health, delivery mode. The context switcher highlights the selected environment's card and filters by customer.
- **States:** only the sandbox ([copy.md](copy.md#empty-states)); drafts (card with "Draft: continue setup" as its primary link); disabled (muted card, "Disabled" word).
- **Viewer:** cards and Open; Add environment and Test connection disabled "Admin only".
- **Acceptance:** each card shows customer, kind, model, health word, Splunk and CIM versions and delivery mode; a card's attention lines match the environment's failing checks in the fixture.

### Customers tab

- Table: customer (display name and slug), environments (dedicated and shared, with index pattern on shared ones), data policy summary (hosted models allowed yes or no, retention days), add-ons running. Primary action: Add customer (admin): display name, slug (`^[a-z0-9-]{2,32}$`), data policy.
- Customer page `/environments/customers/<customer>`: overview of their environments, indexes per shared environment, HFs and HF-DS, data policy (editable by admin, effective value and source shown), add-ons and versions they run, recent runs and deployments.

### CIM library tab (Phase 17c)

- **Purpose:** hold the uploaded `Splunk_SA_CIM` packages, one per version, that CIM work uses.
- **Primary action:** Upload Splunk_SA_CIM (admin).
- **Content:** table: version, SHA-256, uploaded by and when, models read, environments on this version (installed), sandboxes on this version; "Missing" rows for versions installed somewhere with no upload, each with "Upload Splunk_SA_CIM <version>" and the add-on's Splunkbase page link.
- **Upload:** file `.tgz` or `.spl`; code reads `default/app.conf`; result shows version, models found and any refusal ("Version 5.3.0 is outside the compatibility table: Splunk Enterprise 10.2 to 10.6 need 6.3.0 or later"). Notes in the dialog: "Parsemaxxing never ships or fetches this package; it is stored only in this install."
- **Acceptance:** a version installed in an environment with no upload appears as a Missing row; a hostile package (traversal, links, oversized member) is refused with the reason.

## Environment page

Header (sticky on every tab):

```
=========================== (4 px band in environment colour) ===========================
Environments / globex-prod
## globex-prod   [Production] [Dedicated]   Customer: Globex   [ok] Healthy   Splunk 10.6.1 · CIM 8.5.1
Tabs: Overview | Connection | Credentials | Deployment | CIM and versions | Sandbox | Data policy | Discovery and drift | History | Danger zone
```

Tab order (7.13), with which kinds show each:

| Tab | Production dedicated | Production shared | Sandbox | Built in |
| --- | --- | --- | --- | --- |
| Overview | yes | yes | yes | 17 |
| Connection | yes | yes | yes | 17 (relay 18) |
| Credentials | yes | yes | yes | 17 |
| Clients and indexes | no | yes | no | 17 |
| Deployment | yes | yes | no | 17 (targets diagram 18) |
| CIM and versions | yes | yes | yes | 17c |
| Sandbox | yes | yes | no (sandboxes show "Linked production environments" on Overview) | 17 |
| Data policy | yes | yes | no | 17 (retention 21) |
| Discovery and drift | yes | yes | no | 21, 22 |
| History | yes | yes | yes | 17 |
| Danger zone | yes | yes | yes | 17 |

Tabs are a `tablist` with each tab a link (own URL), so a tab can be bookmarked and the back button works. A tab with a problem shows an icon plus a screen-reader word in its label ("Credentials, 1 warning").

### Overview tab

- **Purpose:** is this environment usable, and what runs where.
- **Content:** health summary (last test per node, age); attention list with fixes; versions (Splunk per node, CIM installed, matching library upload, sandbox versions, mismatch warning); **what runs where**: add-ons and versions per tier (search heads, each HF or HF server class; shared: shared search heads and per customer HFs); recent deployments; open drift signals.
- **Primary action:** Run all tests (admin).

### Connection tab

- **Purpose:** the nodes, their roles and how Parsemaxxing reaches each.
- **Primary action:** Run all tests (admin).
- **Content:** node table: host, roles (multi: search head, SHC deployer, SHC member, cluster manager, indexer, heavy forwarder, deployment server; HF-DS and DS for HFs shown as combined labels with tooltips), customer (shared), Splunk version, connection used (rows of the 7.1 connection table that apply: REST read, REST deploy, relay SSH), last test (time, result word), Test button.
  - **How each HF will receive the package** (the 7.1 rule, always visible): "hf1: client of ds-hf1 (DS for HFs): through ds-hf1, server class `pmx_hf_globex`"; "hf-ds1: HF-DS, not a client of a DS for HFs: installed directly". Indexers and cluster managers: "Recorded for discovery and read-only checks. Never receives packages."
  - Node detail drawer: test steps (DNS, TCP, TLS with certificate details, token auth, capabilities compared with what this node needs, version, cluster role, token expiry; relay: host key fingerprint, `status`), each with pass or fail and the fix.
  - "Re-discover" re-reads topology and proposes changes (added, removed, role changed) for confirmation; nothing changes without a tick.
  - "Add node", "Edit", "Remove node…" (admin).
- **Set up relay** (per deployer or DS for HFs, Phase 18), a stepped panel:
  1. Host, port, OS user (default `splunk`); option "Use a dedicated user `pmxrelay` (stricter policy)".
  2. Key: "Generate a key for this environment and host" (default) or "Upload your own private key". The private key is never shown.
  3. The `authorized_keys` line for the chosen option, read-only, with Copy; for `pmxrelay`, also the sudoers line.
  4. Install instructions: link to the relay package and its README, `SHA256SUMS` check command, two checks the test runs (login shell, write access to the apps directory).
  5. Confirm host key: fingerprint shown; the command to compare it on the host; "The fingerprints match" button (admin), which pins it.
  6. Splunk login for this relay host (separate entry, on the Credentials tab): link there.
  7. Test: runs `status`.
  If a pinned fingerprint changes later: the node is Failing, every relay call refused, and the drawer offers "Review new fingerprint…".
- **States:** handoff-only (the table has no Test buttons; "No connection: Parsemaxxing has no network path to this environment. Topology and versions are entered by hand." with "Edit topology").

### Credentials tab

- **Purpose:** every token, key and CA for this environment, without ever showing a value.
- **Content:** per node, one row per credential kind: read token, deploy token (managed), relay SSH key (machine login), relay Splunk login (separate entry, own test), CA bundle (integrity-protected, not secret), webhook token (drift). Columns: kind, used for, status ("Set, updated 3 days ago" / "Not set"), expires (days left, warning at 14 and 3 days), last verified, actions (Replace…, Test, Rotate key… for relay keys, Revoke…).
- **Write-only fields:** inputs are empty with "Enter a new value to replace it"; paste allowed; the value is never sent back. Placeholder never looks like a value.
- **"Show the Splunk role script":** the generated script that creates `parsemaxxing_read` (and `parsemaxxing_deploy`) for the Splunk admin to run, with Copy; Parsemaxxing never creates roles in production.
- **Viewer:** statuses and expiry only.
- **Acceptance:** the response for this tab contains no secret values (Playwright checks network payloads for `pmxt_`, `-----BEGIN` and token-like strings from the fixture); rotating a relay key shows the new line and keeps the old key in use until the new test passes.

### Clients and indexes tab (shared only)

- **Purpose:** keep each customer's data and HFs separate on a shared Splunk.
- **Content:** index naming convention (`cus_<client>_*`) with a live example ("Globex → `cus_globex_*`"); per customer: derived allowlist, exceptions (add, remove), live preview of matching indexes found in the environment, its HFs, HF-DS, optional DS for HFs, per-customer overrides (only settings marked overridable).
- **Rules shown:** "Every HF and DS here belongs to exactly one customer." Unassigned nodes are listed at the top as a warning.
- **Acceptance:** an index matching two customers' patterns is flagged as a conflict and blocks saving.

### Deployment tab

- **Content:** delivery mode (Handoff or Managed, with a one-line explanation of each); rollout order (fixed: heavy forwarders, then search heads; shown, not editable); four-eyes approval (off by default); version mismatch with sandbox: warning or blocking; restart policy note; **targets diagram** (Phase 18): search heads (SHC via deployer, or each SH), HFs (directly or through the DS for HFs), indexers greyed "Never a target", the deployment server for universal forwarders greyed "Never used", with a text list equivalent next to it.
- **Acceptance:** the diagram has a text alternative listing every node and how it receives the package.

### CIM and versions tab (Phase 17c)

- Installed CIM (read or entered), matching library upload (or "Upload Splunk_SA_CIM 8.5.1"), Splunkbase page link; Splunk version per node; spec bundle per version (upload for production versions, with the `tar` command and Copy; automatic for the sandbox); **local changes check**: per data model, "Same as package" or "Modified in this environment" with a diff, and the choice "Runs use: package definitions / this environment's definitions" (admin).

### Sandbox tab

- Linked sandbox (picker of sandbox environments only), its Splunk and CIM versions next to this environment's, mismatch warnings; "Install CIM 8.5.1 on sbx-10-6 from the library" when the sandbox differs (admin, recorded in the ledger). Note: "Every run for this environment is tested on sbx-10-6. Testing never happens on production."

### Data policy tab

- Hosted models allowed (yes or no), masking options, real-data retention (0 to 30 days, default 30; "No setting allows more than 30 days"), "mask raw samples for viewers" (platform default shown with source). On a shared environment, per customer rows. Every row uses the [setting row pattern](#setting-row-inherited-and-overridden).

### Discovery and drift tab (Phases 21, 22)

- Discovery: read account used, time window default, which indexes are in scope (per customer on shared). No schedule (discovery is manual only).
- Drift: monitoring on or off, the monitoring app's deployment status (it is deployed through the deployment pipeline), webhook URL (token part shown as "Set"), source IP allowlist (documentation ranges in examples: 192.0.2.0/24), dedup and cooldown per add-on, "Ask before starting an update run".

### History tab

- Settings history for this environment (and its customers on shared): when, who, setting, old and new value (secrets: "changed"), scope. Filters: scope, setting group, user, date. Export as JSON (non-secret). "What changed on globex-prod last week" is the default filter preset "Last 7 days".

### Danger zone tab

- Disable environment… (stops runs, discovery, deployments and tests; reversible).
- Export settings (non-secret JSON) and Import settings (diff shown before apply).
- New environment from this one (non-secret clone into a draft).
- Remove environment… (typed name): "Removes nodes, credentials, relay keys and settings. Add-on versions, deployment history and the ledger are kept."

## Setting row: inherited and overridden

Every setting on every environment tab and on Settings pages uses one row pattern:

```
Real-data retention                                         [30 days    v]
Days real samples are kept after a run ends. Example: 7.
Inherited from platform default (30 days)
---------------------------------------------------------------------------
Real-data retention                                          [ 7 days   v]   [Reset to inherited]
Set for this environment by Avery, 2026-11-10. Platform default: 30 days.
---------------------------------------------------------------------------
Hosted models allowed                                          No (locked)
Managed by environment variable <NAME> (the real variable name is shown). Change it where the stack is configured, not here.
---------------------------------------------------------------------------
Rollout order                     Heavy forwarders, then search heads (fixed)
Set at platform level; can't be changed per environment.
```

| Source word | Meaning | Editable here |
| --- | --- | --- |
| Default | Built-in value | Yes, creates an override |
| Inherited from platform | Platform setting | Yes if overridable; else "can't be changed per environment" |
| Set for this environment | Override at this level | Yes, with Reset to inherited |
| Set for this customer (shared only) | Override for one customer | Yes, on that customer's row |
| Managed by environment variable | Bootstrap or env-var override | No, read-only with the variable name |

Rules: the source line is text, not only an icon; overrides have a left bar and the word "Override"; "Reset to inherited" shows the value it will return to before confirming; advanced settings collapse under "Advanced" with a count ("Advanced, 2 overrides").

## Add-environment wizard

`/environments/new`, resumable as a draft. Steps, left rail with state words, one step on screen. Flow detail and failure handling: [flows.md F3](flows.md#f3-connect-an-environment-phase-17).

```
Add environment                                                     [Save draft]
1 Type and customer      [done]   | ## Step 3 of 9: Entry search head
2 How Parsemaxxing connects [done]|
3 Entry search head      [now]    | Search head URL
4 Discover and confirm nodes      | [ https://sh1.globex.example.com:8089           ]
5 Clients and indexes (shared)    | One search head (or the standalone). Parsemaxxing finds the rest.
6 Sandbox and CIM                 |
7 Delivery                        | Read token (parsemaxxing_read)        [Show the Splunk role script]
8 Run all tests                   | [ ••••••••••••••••••                            ]
9 Done                            |
                                  | CA bundle  [Upload .pem]   Verify TLS: On
                                  |
                                  | Creating: globex-prod · Globex · Production · Dedicated
                                  |                              [Back]  [Continue]
```

| Rule | Detail |
| --- | --- |
| What is being created is always shown | The line "Creating: <name> · <customer> · <kind> · <model>" sits above the buttons on every step, with the chosen colour swatch |
| Inline validation | On blur and on Continue; errors under the field and in a summary at the top |
| No redundant entry | Values entered once are reused (customer, name) and never asked again (WCAG 3.3.7) |
| Drafts | Saved on Continue and by "Save draft"; listed on the Environments list; nothing in a draft is used by runs or deployments; secrets entered in a draft are stored in the vault under the draft and deleted with it |
| Activation | Only after every test passes in step 8; a failing optional item (relay not yet set up in managed mode) is listed with "Finish later on the Connection tab" |
| Leaving | Leaving mid-step keeps the draft; the browser's unsaved-changes prompt appears only for unsaved input |
| Clone | "New environment from this one" opens the wizard at step 1 with non-secret values prefilled and a note listing what was not copied |
| Handoff only | Step 2 choice; steps 3 and 4 become "Enter topology" and "Enter versions"; step 8 becomes "Review" (no tests) |

**Acceptance:** completing the wizard by keyboard; reloading resumes at the same step; a failing node test keeps the environment as Draft with the fix shown; no step shows another environment's values (fixture with two environments asserts the other's name and hosts never appear in the DOM).

## Isolation walkthrough

The owner's test: **can an admin set up a second environment without touching or seeing the first one's settings?** Walkthrough against this spec, with `globex-prod` already active and `initech-prod` to be added.

| # | Admin does | What they see | Could they touch or see globex-prod? |
| --- | --- | --- | --- |
| 1 | Environments → Add environment | Wizard step 1, empty | No: the wizard loads no existing environment |
| 2 | Dedicated, new customer Initech, name `initech-prod`, colour | "Creating: initech-prod · Initech · Production · Dedicated" | No |
| 3 | Entry search head, token, CA | Fields empty; CA picker offers only "Upload" (no CA from other environments) | No: pickers are scoped to the new environment |
| 4 | Discover and confirm nodes | Only nodes the entry search head reports | No. If the same host is already registered in globex-prod, the row says "Also registered in globex-prod". It names the environment, because the admin needs to know, and shows nothing else about it. |
| 5 | Sandbox and CIM | Sandbox picker lists sandboxes (shared resources by design, D1) with their versions | Sees sandboxes only, not globex-prod's settings |
| 6 | Delivery, Run all tests | Tests name initech hosts only | No: tests are scoped |
| 7 | Done → initech-prod Overview | Header band in Initech's colour | No |
| 8 | Edit initech-prod data policy | Setting rows show "Inherited from platform" or "Set for this environment" | No: inheritance is from platform, never from another environment |

Two findings from the walkthrough that this spec resolves:
- **Shared sandbox:** a sandbox can be linked to several production environments. The Sandbox tab says "Also linked to 1 other environment" (count only), because changing the sandbox's CIM version affects every run that uses it; the install action names the affected environments in its confirmation.
- **Same host in two environments** (step 4): allowed, flagged with the other environment's name only.

Pass criteria for the Phase 17 UX review: the admin completes steps 1 to 8 without visiting any globex-prod route, and a DOM check during the wizard finds no globex-prod node host names, credential labels or setting values (the only allowed mention is the environment name in the "Also registered in" notice).
