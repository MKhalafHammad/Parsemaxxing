# Screen specs

Status: **planned**. One section per screen, each marked with the phase that builds it. Environment screens are in [screens-environments.md](screens-environments.md); Settings sub-pages in [screens-settings.md](screens-settings.md). Words follow [copy.md](copy.md); accessibility rules in [accessibility.md](accessibility.md) apply to every screen and are not repeated.

v1 screens (runs board, run workspace, profile review, approval report, TA registry) are marked **v1: rehome into the shell in Phase 15**: they move inside the app shell with their behaviour kept, and each section lists exactly what changes.

## Conventions for every screen

| Concern | Rule |
| --- | --- |
| Header | Breadcrumb, `h1`, one-line description, at most one primary action |
| Context | Customer and environment from the switcher are applied, and the page says so under the title: "Showing Globex · globex-prod. [Show all]" |
| Lists | Filters (in the URL), sort on every column that can be sorted (`aria-sort`), pagination (25 per page default, 100 max, "1 to 25 of 212"), an empty state with the next action, a "no results for these filters" state with "Clear filters" |
| Loading | Skeleton rows with the table header in place, `aria-busy="true"` on the region; never a blank page. Over 10 s: "Still loading…" text. |
| Partial | When one source fails (for example one environment unreachable), show what loaded, plus an inline warning naming what is missing and why |
| Error | The [copy.md error pattern](copy.md#error-pattern) in place of the content, with "Try again" |
| Viewer | Same page, admin actions disabled with "Admin only" (`<AdminOnly>`) |
| Live data | Server-sent events or polling (as v1); updates never move focus; counts and statuses that change are in polite live regions only when the user started the action |
| Progress | Every task over 2 s shows steps or a determinate bar with text ("Checking 3 of 8"), can be left, and is listed where to resume |
| Progressive disclosure | Plain summary first; evidence, conf and raw detail behind "Show evidence", "Show conf", disclosure buttons with `aria-expanded` |

Acceptance checks below are written for Playwright. Each screen also gets: an axe scan with no serious or critical violations in light and dark at 1280 px and 1920 px, and a viewer run asserting every admin control is absent or disabled with the "Admin only" description.

---

## App shell (Phase 15)

- **Purpose:** frame every page with navigation, context and what needs attention. Spec: [information-architecture.md](information-architecture.md#app-shell).
- **Primary action:** none of its own.
- **Content:** sidebar, top bar (context switcher, search, "Needs you" bell, user menu with role badge), environment strip, banners.
- **States:** engine unreachable (full-width alert with retry, the shell stays); kill switch on (banner, visible to all); setup incomplete (banner linking the checklist).
- **Acceptance:**
  - `getByRole("navigation", { name: "Main" })` lists the ten sections in order; the current one has `aria-current="page"`.
  - Selecting customer Globex and environment globex-prod updates the URL query, the top bar shows "globex-prod" and "Production", and navigating to Deployments keeps both.
  - The bell's accessible name includes the count ("Needs you, 3 items").
  - The user menu shows the role word; it contains Profile, Security (MFA), API tokens, Theme, Sign out, Sign out everywhere.
  - At 1023 px the sidebar is a drawer opened by "Menu" and closed with `Esc`, returning focus.

## Sign in, MFA, recovery (Phase 13)

- **Purpose:** get a user in safely, without revealing which accounts exist.
- **Primary action:** Sign in / Verify.
- **Content:** product name, user name, password (show/hide toggle), Sign in; MFA step: one code field, "Use a recovery code instead"; directory-unavailable note when reported; theme toggle.
- **States:** failure (one generic message), lockout (time to wait as text), session ended (message above the form), setup not done (redirect to `/setup`).
- **Progressive disclosure:** none; nothing technical on this page.
- **Acceptance:** wrong user and wrong password produce identical text and status; paste works in every field; MFA field has `autocomplete="one-time-code"`; after sign-in the user lands on `next` only if it is a same-origin path.

## First-run setup wizard (Phase 15)

- **Purpose:** take a fresh install to a working sandbox with one admin, without docs. Flow: [flows.md F1](flows.md#f1-first-run-setup-phase-15-setup-token-in-phase-13).
- **Primary action:** Continue (per step); Finish.
- **Content:** step list on the left ("Setup token · First admin · MFA · LLM provider · Sandbox · Production environment (optional) · Done") with each step's state as icon plus word; the step form on the right; each field with a one-line explanation.
- **States:** step test running (progress text), step test failed (error pattern with the fix), resumed ("Welcome back. Continue at: LLM provider").
- **Viewer:** not applicable (no users yet).
- **Acceptance:** completing all steps by keyboard alone reaches Overview; the checklist on Overview reflects skipped steps; reloading mid-wizard resumes at the first incomplete step; recovery codes are shown once and Continue stays disabled until "I have saved these codes" is checked.

## Overview (Phase 15; KPIs Phase 19)

- **Purpose:** in 5 seconds, tell anyone what needs attention and whether things are healthy.
- **Primary action:** the first "Needs you" item's action (admin); none for viewers.
- **Content, in priority order:**
  1. Needs you (or "Waiting on an admin" for viewers), grouped by customer and environment, max 6 with "Show all".
  2. Setup checklist (until complete).
  3. Environment health strip: a card per environment in context (name, colour, kind, health word, the one thing wrong).
  4. KPI tiles (Phase 19): runs this week and first-attempt pass rate, versions registered, deployments and failures, open drift signals, cost today against the daily cap. Each tile links to Analytics with the same filters.
  5. Recent activity: last 10 runs and deployments with status.
- **States:** empty install (checklist and "Start your first run"); all good ("Nothing needs you. 4 environments healthy."); partial (one environment unreachable: its card says "Failing" and why).
- **Acceptance:** a viewer sees the same items as an admin with no enabled action buttons; every card's status has an icon and a word; the "Needs you" count matches the bell.

## Runs board (v1: rehome into the shell in Phase 15)

- **Purpose:** every run and what it is doing now.
- **Primary action:** New run (admin).
- **Content:** "Needs you" pinned (kept), table: Run ID, source, kind (build, update, drift), customer and target environment (new), phase, working now (actor identity, kept), attempt, tokens, status, updated. Filters: status, kind, customer, environment, date.
- **Changes from v1:** route `/runs`; column "Job" becomes "Run ID"; new columns customer and environment; filters and pagination; status words from [copy.md](copy.md#runs); a "Real data deleted on" column under "More columns".
- **States:** empty ([copy.md](copy.md#empty-states)), filtered empty, engine error (kept as alert with the error pattern).
- **Acceptance:** existing `e2e/flow.spec.ts` keyboard path still passes after the route change; filtering by environment narrows the rows and is reflected in the URL.

## New run sheet (v1: rehome into the shell in Phase 15; target environment Phase 17)

- **Purpose:** start one run for one log source.
- **Primary action:** Start run.
- **Content:** log file, update an existing add-on, vendor, product, time zone, skip profile review (kept); customer and "Build for" target environment (new); a summary box before Start: sandbox, Splunk and CIM version, data policy (allowed providers), estimated tokens and cost, real data deletion date.
- **States:** policy block (Start disabled, error pattern); CIM missing for target (warning, start allowed, run will be parsing-only); upload rejected (kept checks, error pattern).
- **Acceptance:** keyboard order unchanged from v1 plus the two new fields after Product; the summary updates when the target changes.

## Run workspace (v1: rehome into the shell in Phase 15)

- **Purpose:** follow one run live and understand every decision.
- **Primary action:** the phase's human action when it waits (Confirm profile, Approve version); otherwise none.
- **Keep exactly:** actor identities (`lib/actors.ts`), budget meters, the Now banner, the clickable deep-linkable phase rail (`?phase=&attempt=`), each attempt's proposal, gate verdict, Splunk checks and outcome, row diffs between attempts, backtracks, the activity feed grouped by phase and attempt, raw vs parsed with one colour per field, the editor-style conf view with "Explain settings".
- **Changes:** header gains customer, target environment (with colour) and sandbox used; a "Real data" line ("Real data is deleted on 2026-12-18. [Delete real data now…]" admin); breadcrumb Runs / <run ID>; a Cancel run action under "More" (admin, confirmed). Router actor shown for mixed feeds (Phase 23).
- **States:** loading (skeleton rail), stream disconnected (banner "Live updates paused. Reconnecting…" with retry; data stays), legacy runs (kept display-only fallback).
- **Acceptance:** deep link `?phase=extraction&attempt=2` opens that attempt; the Now banner names the acting agent with its kind word; no unified-diff markers anywhere (existing `xss.spec.ts` kept).

## Profile review (v1: rehome into the shell in Phase 15; format check Phase 17c)

- **Purpose:** let a human confirm what the log is before agents build on it.
- **Primary action:** Confirm profile.
- **Content:** format check card (17c: code's detection vs the Profiler's answer, agree or pick one with evidence), time source, encoding, header lines, field findings with coverage meters (kept), time zone when needed (kept), corrections marked "You changed this" (kept). No data model questions (removed in 17c, 7.16).
- **States:** disagreement unresolved (Confirm disabled with the reason next to it); viewer (read-only values, Confirm disabled "Admin only").
- **Acceptance:** with a fixture where code says CEF and the Profiler says key=value, Confirm is disabled until a format radio is chosen; example lines render as escaped text.

## Approval report (v1: rehome into the shell in Phase 15; data model decision 17c; references 20; preview 18)

- **Purpose:** give an admin the evidence to vouch for a version, and a viewer the record of why it was approved.
- **Primary action:** Approve version… (in the sticky decision bar, kept).
- **Content, in priority order (kept sections first, new ones marked):**
  1. Summary: CIM meters, attempts per phase, holdout (kept).
  2. Decisions the agents made (kept), now with **Data model** (new): summary sentence, per-category choice with fit score and Splunk result, field-level plan, enum mappings with unmapped values and counts, rejected alternatives with reasons, code-bound flags, or "No CIM model fits" with the reason.
  3. How it was validated (kept); preview on production next to the sandbox result (new, labelled extra and read-only).
  4. References used (new): title, tier, version, page; unverified examples labelled.
  5. Raw vs parsed with the CIM view (kept).
  6. Configuration (kept).
  7. Update only: row diff against the version it patches, `local/` overrides (kept). The v1 "rollback command" line becomes "To undo later, revert an environment to 1.2.0 from the add-on page."
- **Decision bar:** SHA-256, Download package, Reject…, Approve version…. Must not obscure the focused element (WCAG 2.4.11): content gets bottom padding equal to the bar.
- **States:** awaiting approval; decided (bar shows "Approved by Avery, 2026-11-18 14:02" and links to the version); real data purged (raw lines replaced by masked ones, banner "Real data was deleted on 2026-12-18; lines shown are masked").
- **Acceptance:** approve dialog names the version and SHA-256 and says it is not deployed anywhere; tabbing to the last element of the report leaves it fully visible above the bar; the data model section lists rejected alternatives with reasons on a fixture with two candidates.

## Discovery (Phase 21; overlay action Phase 21b)

### Scans list `/discovery`
- **Purpose:** see how well Splunk parses data already indexed, per customer and index.
- **Primary action:** Scan index… (admin).
- **Content:** scans table (started, by, customer, environment, index, sourcetypes found, worst verdict, status); findings summary by verdict for the context.
- **States:** empty; environment handoff-only ("Discovery needs the read API; globex-offline has no connection"); scan running (progress per check group).

### Scan dialog
- Customer (shared environments), environment, index (only allowlisted for that customer), optional sourcetype, time window (default 24 h). Shows the read account used and "Discovery stores counts and verdicts, never the events."

### Finding `/discovery/findings/[id]`
- **Primary action:** Start a run from this finding (or Start an overlay fix when owned by another add-on; or Upload the raw file when samples are unusable).
- **Content:** verdict and plain summary; evidence numbers by group (volume and spread, `_time` vs `_indextime` gap distribution as a chart with table toggle, parser warnings, truncation, line merging, field summary, CIM tags and data models, owning app, name quality, mixed shapes); "Show the SPL" per check (read-only text).
- **Acceptance:** an index outside the customer's allowlist is not offered in the dialog, and a crafted URL returns the tenant isolation error; "Start a run" opens the run sheet pre-filled with the environment and sourcetype.

## Add-ons list (Phase 17b; replaces v1 TA registry `/tas`)

- **Purpose:** every add-on, its latest version and where each version runs.
- **Primary action:** none (admins deploy from an add-on); "New run" as a secondary link when empty.
- **Content:** table: add-on (app name in monospace, vendor and product), sourcetype(s), latest version, versions count, where it runs (compact per environment, filtered by context), behind count ("2 environments behind"), overlay badge for overlay add-ons (21b). Filters: vendor, environment, behind only, deprecated.
- **Changes from v1:** route `/addons` (v1 `/tas` redirects); title "Add-ons" (was "TA registry"); version list becomes the add-on page.
- **Acceptance:** with fixtures for three environments, the "where it runs" cell lists each with the version per tier; `/tas` redirects.

## Add-on page `/addons/[app]` (Phase 17b; Where it runs per production environment from Phase 18)

- **Purpose:** answer "which version runs where, and what are the versions?"
- **Primary action:** Deploy… (admin).
- **Content, in priority order:**
  1. **Where it runs**: environments grouped by customer; rows per tier (search heads, heavy forwarders; for shared environments, the shared search heads and each customer's HFs); version per row; "Newer version available: 1.4.0" with "Deploy 1.4.0…"; last deployment link.
  2. **Versions**: timeline newest first: version, badges (Latest, Deprecated, Integrity failed, No regression set), approved by and when, source run, parent version, changelog summary (from the row diff), events between versions (reverts, roll forwards, deprecations). Toggle "Lineage tree" (a tree list with `role="tree"`, keyboard arrows, no drag).
  3. Actions per version row: View, Compare with…, Download, Deploy this version… / Revert an environment to this version….
- **States:** one version only (compare disabled with "Needs two versions"); no environment runs it ("Not deployed anywhere yet. [Deploy…]").
- **Acceptance:** from the add-on page, a user reaches the 1.2.0 → 1.4.0 compare and sees what globex-prod runs within 3 interactions from the add-on page; the lineage tree shows a branch for a fixture with revert then update.

## Version page `/addons/[app]/versions/[v]` (Phase 17b)

- **Purpose:** everything about one immutable version.
- **Primary action:** Deploy this version… (admin); for an older version the label is "Revert an environment to this version…".
- **Tabs:** Overview · Files · Changelog · Where it runs.
  - Overview: SHA-256 of the promoted and tested packages (copyable), run, approved by and when, parent, deprecation reason, masked regression set status, CIM version and definition hash it was tested with, Splunk version of the sandbox.
  - Files: tree (allowlisted files only) and viewer (`?file=` deep link); `.conf` in the editor pane with "Explain settings"; CSV as a table; size-capped with a message.
  - Changelog: the row-diff summary against the parent.
- **More menu:** Compare with…, Compare with installed…, Download tested package, Deprecate… (admin).
- **States:** integrity failed (red banner, download and deploy disabled, "Report sent to Security health"); deprecated (amber banner with reason; deploy needs typed confirmation).
- **Acceptance:** a file path not in the version's list returns an error state, never a file; `../` in `?file=` is refused; viewer can download and compare, deploy and deprecate are disabled.

## Compare versions `/addons/[app]/compare?from=&to=&file=` (Phase 17b)

- **Purpose:** show exactly what changed between any two versions.
- **Primary action:** none (viewing). "Copy link" is the main secondary.
- **Content:** two pickers (from, to), Swap; summary sentence and counts; file list with added, removed, changed (icon plus word); per selected file: setting-level diff (stanza, key, from value, to value, change word) as rows, then side-by-side text with row tints and words, no unified-diff markers.
- **States:** same version picked twice ("Pick two different versions"); non-adjacent and across a revert both work, with a note "1.2.0 was reverted to on globex-prod between these versions".
- **Acceptance:** deep link with `file=default/props.conf` opens that file; swapping updates the URL; no `+`/`-` line prefixes or `@@` markers.

## Compare with installed `/addons/[app]/compare-installed?version=&environment=` (Phase 17b on the sandbox; per production environment Phase 18)

- **Purpose:** show drift between the registry and what an environment actually runs.
- **Content:** environment header with colour and customer; tier picker; per setting: version value, effective value on the target, source on the target ("from this add-on", "set in local/", "from another app: <app>").
- **States:** handoff-only (not available, says why); token can't read configs (partial, lists what couldn't be read).

## Deployments list `/deployments` (Phase 18)

- **Purpose:** every deployment, its state and what needs approval or attention.
- **Primary action:** New deployment (admin).
- **Content:** table: ID, add-on and version, customer, environment (colour, kind), tiers, mode (handoff, managed), requested by, approved by, status with step, updated. Filters: status, environment, customer, add-on, mode. "Needs you" deployments pinned.
- **Acceptance:** filtering by environment from the context switcher narrows rows; a failed row shows "Failed at verify (search heads)".

## New deployment dialog (Phase 18)

- **Purpose:** pick the version and the environments; nothing is deployed by default.
- **Content:** add-on and version (prefilled when opened from a version); customer; environments for that customer (dedicated, then shared where the customer has indexes, each with health, current version per tier, delivery mode); multi-select; "Preview on production" option (second, off by default). "Create plans" creates one deployment per environment and lists them.
- **States:** environment failing or not supported (unselectable with the reason); deprecated version (typed confirmation in this dialog).
- **Acceptance:** with nothing ticked, "Create plans" is disabled; ticking two environments creates two deployments with separate pages.

## Deployment page `/deployments/[id]` (Phase 18)

- **Purpose:** take one version to one environment safely and show the proof.
- **Primary action:** the current step's action (Request approval, Approve deployment…, Mark delivered…, Roll back…).
- **Content:**
  1. Header: add-on and version, SHA-256, **customer and environment with colour and kind**, mode, status.
  2. Step rail (pattern from the run workspace's phase rail): Plan · Impact · Approval · Delivery · Verify, each with state word.
  3. Plan: target table (node, roles, tier, included or left out, how, why); order (HFs then search heads); not-deliverable notes ("index-time part not deliverable: this data does not pass through a heavy forwarder").
  4. Impact: checks with result and "Show evidence"; shared search head check per customer (safe or blocking with fields lost); restart needed; existing stanzas and `local/` overrides; customers and indexes receiving the sourcetype.
  5. Delivery: per tier progress; **live relay console** (read-only terminal view: command, output, exit code, timestamps, request id; secrets masked; replayable; `role="log"`); handoff runbook with copy buttons and "Copy all as a script" (tokens as `<your token>`).
  6. Verify: per tier results; smoke search status with waiting text.
  7. History: deployment events.
- **States:** awaiting another admin (four-eyes); failed (step and tier named, Roll back…); cancelled; handoff-only skips verify with a manual checklist.
- **Acceptance:** the approve dialog contains the environment name, the customer and the full SHA-256; the console region has `role="log"` and no input; for a plan with an indexer, the indexer row reads "Never a deployment target"; a UF server class is never in the included targets.

## Drift (Phase 22)

### Drift list `/drift`
- **Purpose:** format changes seen in production, per environment and add-on.
- **Primary action:** none; per row Open.
- **Content:** signal, environment, customer, add-on, first seen, events affected, Drift Analyst verdict, status, linked run and deployment. Filters by status, environment.
- **Empty:** monitoring off (link to the environment's Discovery and drift tab) or no signals.

### Drift page `/drift/[id]`
- **Primary action:** Open the update run (when one exists) or Start update run (admin).
- **Content:** what changed (plain), evidence (masked samples, check failures), Drift Analyst decision with reason, the update run, the proposed deployment ("Proposed for globex-prod only. Needs approval."), other environments running the add-on.

## Knowledge (Phase 20; spec bundle upload in 17c)

- **Overview `/knowledge`:** per environment Splunk version, the manuals checklist (priority 1 and 2, imported or missing, with the manual-page link), spec bundle and CIM tier status per version, retire unused sets. Primary action: Import documents (admin).
- **Sources `/knowledge/sources`:** table: source, tier (1 to 8 with names), status, versions, chunks, last indexed, approved by. Quarantined first. Row actions: Approve source…, Reject source…, Re-index, Retire (admin).
- **Import `/knowledge/import`:** files or folder (`<product>/<version>/<manual-id>/<file>.pdf`), or a signed pack; pre-import table showing detected product, version, manual and any disagreement with the PDF's own text, duplicates skipped, refusals (below 10.2, no text layer, over size). Progress per file.
- **Test retrieval `/knowledge/retrieval`:** query box, filters (tier, version), results with score, tier, version, page.
- **Acceptance:** a quarantined source is never shown as used in a run; a refused file lists the reason; viewer sees sources and can test retrieval (read-only) but not import or approve.

## Analytics (Phase 19)

- **Purpose:** trends and drill-down for runs, add-ons and deployments, cost and models, environments, knowledge (7.8).
- **Primary action:** none.
- **Content:** area tabs (Runs · Add-ons and deployments · Cost and models · Environments · Knowledge); filters (time range, customer, environment, add-on, provider, model) in the URL, synced with the context switcher; each chart: title, one-line takeaway in text ("First-attempt pass rate 62%, up from 55% last week"), the chart, a "Show as table" toggle, and drill-down links to the runs or deployments behind each point.
- **Chart rules:** colours from tokens; series also differ by marker or dash and are labelled directly; no information by colour alone; keyboard focus on data points shows the value; reduced motion respected.
- **Acceptance:** every chart has a table toggle whose table matches the chart's data; drill-down opens the runs list with the same filters.

## User menu pages (Phase 13 back end, Phase 15 screens)

- **Profile `/me`:** display name, user name, role (read-only), source (local or LDAP), theme (light, dark, system), sidebar default, default context.
- **Security `/me/security`:** change password (local only), MFA enrol or reset own, recovery codes (create new, shown once), active sessions with device, IP and last seen, "Sign out everywhere".
- **API tokens:** see [screens-settings.md](screens-settings.md#api-tokens), filtered to own tokens.
- **Acceptance:** changing the password signs out other sessions and says so; recovery codes are shown once.

## Search results `/search?q=` (Phase 15)

- Grouped results as in [information-architecture.md](information-architecture.md#global-search), with type filter chips and pagination; empty state with suggestions.
