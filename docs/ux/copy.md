# UX copy and terminology

Status: **planned**. Applies to every screen from Phase 15 on; v1 screens adopt it when they are rehomed into the shell in Phase 15. The `frontend` agent keeps status words in one place in code (`web/lib/status.ts` today) and takes them from this file.

## Voice

- Plain, short, direct. Sentence case for everything (titles, buttons, tabs). No exclamation marks, no emoji.
- Name the thing: the add-on, the version, the customer and the environment, every time it matters. "Deploy TA-parsemaxxing-acme-fw 1.3.0 to globex-prod" beats "Deploy this".
- Say who acts: "The Validator ran 14 checks", "Code found 3 search heads", "You approved". Agents propose, code acts, Splunk judges, a human approves; copy keeps that visible.
- Numbers with units and counts: "40 of 40 events", "3 days left", "2 search heads, 4 heavy forwarders".
- Times: relative with the absolute time on hover and in the accessible name ("5 minutes ago", `2026-11-18 14:02 UTC`). Absolute times are shown in the user's time zone with the zone named; ledger exports use UTC.
- Name the licence only as PolyForm Shield 1.0.0 (About page), never with another licence label. Never mention any assistant or tool as an author.
- Examples in the UI, docs and fixtures use only Acme, Globex, Initech, `example.com` and the documentation IP ranges (192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24).

## Vocabulary (one word per concept)

| Use | Not | Meaning and notes |
| --- | --- | --- |
| add-on | TA, app, parser, package (in UI headings) | The thing Parsemaxxing builds. "TA" only in technical detail: the app name `TA-parsemaxxing-<vendor>-<product>`, conf views, commands. |
| version | release, build | One immutable, registered version of an add-on, for example `1.3.0` |
| package | bundle (except "handoff bundle"), tarball | The `.tgz` file of a version; always shown with its SHA-256 |
| run | job, build job, task | One build, update, drift or discovery job. "Run ID" for the identifier. Kinds: "build run", "update run", "drift run". Discovery is a "scan", not a run. |
| scan | discovery run | A discovery pass over an index or sourcetype |
| finding | result, issue | One discovery verdict for an (index, sourcetype) |
| deployment | rollout, push, release | One version on one environment, with its plan, approval, delivery and verification |
| plan | deployment plan (after first use on a page) | Code's list of targets and how each gets the package |
| impact | impact analysis (in headings), blast radius | The read-only checks before approval |
| deliver, delivery | push, install (as the step name) | The step that puts the package on the targets. "Install" is fine for one node. |
| verify, verification | validate (reserved for the Validator) | Post-deploy read-only checks |
| revert | downgrade, rollback (for this meaning) | Install an older version on an environment, by a new deployment. Newer versions are kept. |
| roll back | undo, revert (for this meaning) | Offered on a failed or unwanted deployment: install the version each tier ran before, through the same pipeline |
| roll forward | upgrade, redeploy | Deploy a newer version again after a revert |
| deprecate | delete, retire, archive | Mark a version not recommended. It stays viewable, downloadable and deployable with a typed confirmation. There is no delete. |
| approve | accept, sign off | Admin decision on a version (build) or a deployment. Always "Approve version" or "Approve deployment" in buttons, never bare "Approve" in v2. |
| reject | decline, deny | Admin decision that ends a run without a version |
| environment | Splunk, instance, cluster, site | One Splunk Enterprise deployment Parsemaxxing knows. Kinds: production or sandbox. |
| sandbox | test Splunk, lab | A standalone Splunk where every run is tested (D1) |
| production environment | prod (except in names) | An environment that runs approved add-ons |
| dedicated environment | single-tenant | Belongs to one customer |
| shared environment, "Shared (MSSP)" as the badge | multi-tenant, MSP environment | Serves several customers, isolated by indexes and their own HFs (D3) |
| customer | client, tenant, organisation | A tenant. The owner's word "client" appears only in quoted requirements; the UI says customer. |
| node | host, server, instance | One Splunk host in an environment; a node has one or more roles |
| search head | SH (except in diagrams and tables with a legend) | |
| search head cluster | SHC (except in technical detail) | |
| SHC deployer, "deployer" after first use | | |
| heavy forwarder, HF | | "HF" allowed after first use on a page and in tables |
| HF-DS | "HF/DS", "DS HF" | A heavy forwarder that is also the deployment server for universal forwarders. Tooltip: "Heavy forwarder that is also the deployment server for universal forwarders" |
| DS for HFs | HF deployment server, DS | A dedicated deployment server that manages heavy forwarders. Tooltip: "Deployment server that manages heavy forwarders" |
| deployment server for universal forwarders | UF DS | Spelled out; Parsemaxxing never deploys through it |
| indexer | | Always with "never a deployment target" where targets are listed |
| relay | SSH agent, jump host | `pmx-relay` on a deployer or DS for HFs |
| handoff, handoff mode | manual mode | Parsemaxxing prepares, a Splunk admin delivers |
| managed, managed mode | automatic mode | Parsemaxxing delivers |
| connection test | health check, ping | Per-node test |
| health | status (for environments) | Healthy, Warning, Failing, Not tested, No connection |
| credential | secret (in labels) | Token, key or password stored in the vault. "Secret" only in Settings > Security health and docs. |
| token | API key (for Splunk tokens and `pmxt_` tokens) | Splunk token or Parsemaxxing API token; always say which |
| sample, samples | logs (as the object), events (before indexing) | The uploaded or pulled log lines |
| event | line, record | One Splunk event after line breaking |
| real data | PII, sensitive data | Samples and anything containing raw lines (7.19). "Real data is deleted on 2026-12-18." |
| masked | anonymised, redacted, obfuscated | Replaced by consistent fake values (7.10) |
| profile | analysis | The Profiler's description of the log |
| check | test (for Validator items), assertion | One Validator SPL check, pass or fail |
| attempt | try, iteration | One proposal and its checks within a stage, "attempt 2 of 5" |
| stage | phase (for index-time, extraction, CIM) | Index-time, Extraction, CIM mapping. "Phase" is the rail item, which also covers profile and approval. |
| data model | CIM model, DM | "Network_Traffic data model" |
| overlay, overlay add-on | patch, fix add-on | `TA-parsemaxxing-overlay-<vendor>-<product>` (name pending Q23) |
| drift signal | alert, drift event | A detected format change on an environment |
| knowledge source | document, corpus | One item in Knowledge |
| ledger | log, history (for the hash-chained record) | The append-only record of everything a run did |
| audit log | security log | Logins, setting changes, approvals, downloads |
| inherited, set for this environment, set for this customer, default, managed by environment variable | global, local, custom | Source of an effective setting value |
| admin, viewer | administrator, read-only user | The two roles (D6) |

## Status words

Each status is an icon, a word and a colour token; never colour alone. Tones: running (blue, spinning loader that stops with `prefers-reduced-motion`), waiting (amber, hand), good (green, check), bad (red, cross), neutral (grey, circle), warning (amber, triangle).

### Runs

| Engine status | Word | Tone | Change from v1 |
| --- | --- | --- | --- |
| `queued` | Queued | running | |
| `running` | Running | running | |
| `profile_review` | Needs profile review | waiting | |
| `awaiting_approval` | Awaiting approval | waiting | |
| `approved` | Approved | running | |
| `promoting` | Registering version | running | Was "Promoting". In v2 a build ends in the registry, not on an environment (D7). |
| `done` | Version registered | good | Was "Promoted". The engine owner confirms the v2 status names in Phase 17b/18. |
| `rejected` | Rejected | bad | |
| `stage_failed` | Stage failed | bad | |
| `error` | Error | bad | |
| `smoke_failed` | Smoke test failed | bad | |
| `promotion_failed` | Registration failed | bad | Was "Promotion failed" |
| `cancelled` | Cancelled | neutral | New |
| expired (waiting on a human for 30 days, 7.19) | Expired | neutral | New |

### Deployments

| Status | Word | Tone | Note |
| --- | --- | --- | --- |
| `planned` | Planned | neutral | |
| `awaiting_approval` | Awaiting approval | waiting | Four-eyes: "Awaiting another admin" for the requester |
| `delivering` (managed) | Delivering | running | With the current tier: "Delivering to heavy forwarders (2 of 4)" |
| `delivering` (handoff) | Waiting for delivery | waiting | "Mark delivered" is the admin's action |
| `verifying` | Verifying | running | |
| `deployed` | Deployed | good | |
| `failed` | Failed | bad | Always followed by the step: "Failed at verify (search heads)" |
| `rolled_back` | Rolled back | neutral | |
| `cancelled` | Cancelled | neutral | |

### Add-on versions

| State | Word | Tone |
| --- | --- | --- |
| latest registered | Latest | good |
| older, not deprecated | (no badge) | neutral |
| deprecated | Deprecated | warning |
| hash mismatch in the store | Integrity failed | bad |
| masked regression set missing | No regression set | warning, with "updates will need fresh samples" |

Where it runs: "Runs on globex-prod (search heads, heavy forwarders)"; "Newer version available: 1.4.0" (warning, never automatic).

### Environments and nodes

| State | Word | Tone |
| --- | --- | --- |
| all node tests pass | Healthy | good |
| a warning (token expiring, version mismatch, CIM upload missing) | Warning | warning |
| a node test fails | Failing | bad |
| never tested | Not tested | neutral |
| handoff-only, no network path | No connection (handoff only) | neutral |
| below Splunk 10.2 | Not supported | bad |
| draft from the wizard | Draft | neutral |
| disabled | Disabled | neutral |

### Discovery verdicts

| Verdict | Word | Tone |
| --- | --- | --- |
| `healthy` | Healthy | good |
| `needs index-time fix` | Needs index-time fix | warning |
| `needs extraction` | Needs field extraction | warning |
| `needs CIM mapping` | Needs CIM mapping | warning |
| `mixed feed: routing needed` | Mixed feed: needs routing | warning |
| `owned by another app: overlay fix possible` | Owned by another add-on: overlay fix possible | warning |
| `samples unusable: upload the raw file` | Samples unusable: upload the raw file | bad |

### Drift

Open · Analysing · Not a real change (dismissed by the Drift Analyst or an admin) · Update running · Deployment proposed · Resolved.

### Knowledge sources

Quarantined · Approved · Rejected · Indexing · Indexed · Failed · Retired.

## Button labels

Verbs, sentence case, naming the object when the screen has more than one. A trailing ellipsis means a dialog follows.

| Context | Primary | Secondary | Destructive or production |
| --- | --- | --- | --- |
| Runs board | New run | | |
| New run sheet | Start run | Cancel | |
| Profile review | Confirm profile | Reset my changes | |
| Approval report (build) | Approve version… | Download package | Reject… |
| Add-on page | Deploy… | Compare versions, Download | |
| Version page | Deploy this version… | Compare with…, Compare with installed…, Download | Deprecate… |
| Compare | (none; viewing) | Swap, Download both | |
| Deployments list | New deployment | | |
| Deployment, planned | Request approval | Edit targets, Cancel deployment | |
| Deployment, awaiting approval | Approve deployment… | Download plan | Cancel deployment… |
| Deployment, handoff | Mark delivered… | Copy all as a script, Download bundle | |
| Deployment, failed | Roll back… | Retry verification, Download transcript | |
| Discovery | Scan index… | | |
| Finding | Start a run from this finding | Start an overlay fix | |
| Drift signal | Open the update run | Dismiss… | |
| Environments list | Add environment | | |
| Wizard | Continue, Run all tests, Finish | Back, Save draft | Discard draft… |
| Node | Test connection | Set up relay, Edit | Remove node… |
| Credential | Replace…, Test | | Revoke… |
| Relay key | Rotate key… | Copy line | |
| Setting override | Save | Reset to inherited | |
| Danger zone | | | Disable environment…, Remove environment… |
| Knowledge import | Import documents | | |
| Quarantined source | Approve source… | Test retrieval | Reject source… |
| API tokens | Create token | | Revoke… |
| Users | Add user | Reset MFA… | Disable user… |
| LDAP | Save | Test connection, Test a user lookup | |
| Retention | | | Delete real data now… |
| Kill switch | | | Stop all model calls… |

Never: "OK", "Submit", "Yes" alone, "Click here".

## Error pattern

Every error shows three parts and a request id, and offers the fix as a link or button where one exists.

```
[x] <What happened, in one sentence.>
    <Why, in one sentence, with the number or name that matters.>
    <What to do, as an action.>                      [Fix action]
    Request id 7f3c1a2e (copy)
```

| Example | What happened | Why | What to do |
| --- | --- | --- | --- |
| Node test, TLS | Couldn't connect to sh1.globex.example.com. | The certificate is not signed by the CA bundle stored for globex-prod. | Upload the CA that signed this certificate, or check the host name. [Replace CA bundle] |
| Node test, version | sh1.globex.example.com runs Splunk Enterprise 9.4.2. | Parsemaxxing supports Splunk Enterprise 10.2 and later. | Upgrade this node, then test again. globex-prod can't be used for runs, discovery or deployments until then. |
| CIM missing | CIM checks are blocked for globex-prod. | No uploaded Splunk_SA_CIM matches 8.5.1, the version installed in globex-prod. | Upload Splunk_SA_CIM 8.5.1. Parsing-only runs still work. [Open CIM library] |
| Egress policy | This run can't start. | Initech's data policy allows only on-prem models, and the Extraction agent is set to a hosted model. | Assign an on-prem model to Extraction, or ask an admin to change Initech's data policy. [Open LLM providers and agents] |
| Tenant isolation | The scan was refused. | Index `cus_globex_fw` is not in Initech's index allowlist on msp-shared-1. | Pick one of Initech's indexes, or edit the allowlist on the Clients and indexes tab. |
| Four-eyes | You can't approve this deployment. | globex-prod requires a different admin to approve, and you requested it. | Ask another admin. It is in their "Needs you". |
| Stale state | This deployment changed while you were viewing it. | Another admin approved it 1 minute ago. | Review the current state. [Reload] |
| Login | Sign-in failed. | (none: one generic message, no user enumeration) | Check your user name and password. After 5 failures, wait before trying again. |
| Session | Your session ended. | You were inactive for 30 minutes. | Sign in again; you will return to this page. |
| Network | Parsemaxxing isn't responding. | The engine could not be reached. | Try again in a moment. If it keeps happening, check `make logs`. |

Rules: no stack traces, internal paths or raw exception text (A10); the request id is the link to the detail in the audit or engine log. Form errors are inline under the field, linked with `aria-describedby`, plus a summary at the top of the form after submit that links to each field. Validation messages state the rule: "Use 2 to 32 lowercase letters, digits or hyphens (for example `globex-prod`)."

## Confirmation dialogs

A confirmation is required for every production action, every irreversible action and every security change. Each one:

1. Title: the verb and the object. "Deploy TA-parsemaxxing-acme-fw 1.3.0 to globex-prod?"
2. **Context block** at the top, always: customer, environment name with its colour swatch and kind badge, and for shared environments "shared by N customers".
3. What will happen, as a short list, in plain words.
4. What will not happen or stays safe (for example "Newer versions are kept").
5. The exact identity: package SHA-256 in full, monospace, copyable.
6. Extra friction by risk: high risk (restart needed, shared stanza, shared search heads, deprecated version) needs the environment name typed; the confirm button stays disabled until it matches.
7. Buttons: Cancel (initial focus) and a confirm button that repeats the verb. Production and destructive confirms use the destructive or production variant.

| Dialog | Title | Body (key lines) | Typed confirmation | Confirm button |
| --- | --- | --- | --- | --- |
| Approve version (build) | Approve TA-parsemaxxing-acme-fw 1.3.0? | Registers exactly this package as version 1.3.0. It is not deployed anywhere; you choose environments later. SHA-256 … | No | Approve version 1.3.0 |
| Reject run | Reject run 3f9a21c0? | No version is registered. The run's real data is deleted on 2026-12-18 (or now, if Globex's retention is 0 days). | No | Reject run |
| Approve deployment | Deploy TA-parsemaxxing-acme-fw 1.3.0 to globex-prod? | Globex · globex-prod (Production, dedicated). Heavy forwarders first (hf1, hf2, directly), then search heads (SHC through deployer.globex.example.com). Restart not required. Indexers are never touched. SHA-256 … | Only when high risk | Approve and deploy |
| Approve deployment, shared | Deploy TA-parsemaxxing-acme-fw 1.3.0 to msp-shared-1 for Initech? | Index-time part: Initech's heavy forwarders only (hf-initech-1). Search-time part: the shared search heads, used by 2 customers; the shared search head check passed for Globex and Initech. | Yes (shared search heads) | Approve and deploy |
| Revert | Revert globex-prod to TA-parsemaxxing-acme-fw 1.2.0? | globex-prod runs 1.4.0 now. This installs 1.2.0's stored package through a new deployment (plan, impact, approval, verify). **Newer versions (1.3.0, 1.4.0) are kept** and can be deployed again at any time. Index-time changes affect only data indexed after the revert. | Yes | Create revert deployment |
| Roll back | Roll back deployment d-0142 on globex-prod? | Heavy forwarders go back to 1.2.0 (what they ran before). Search heads were not changed. Uses the same approval rules. Version 1.3.0 is kept. | Only when high risk | Create rollback deployment |
| Deprecate version | Deprecate TA-parsemaxxing-acme-fw 1.1.0? | It stays viewable, downloadable and comparable. Deploying it will need a typed confirmation. Reason (required). | No | Deprecate 1.1.0 |
| Mark delivered (handoff) | Mark delivery to globex-prod as done? | Confirms that a Splunk admin ran the runbook steps. Verification starts now (read-only). | No | Mark delivered |
| Cancel deployment | Cancel deployment d-0142? | Nothing more is delivered. Tiers already done stay as they are; you can roll them back. | No | Cancel deployment |
| Remove environment | Remove globex-prod? | Deletes its nodes, credentials, relay keys and settings. Add-on versions, deployments history and the ledger are kept. | Yes | Remove globex-prod |
| Rotate relay key | Rotate the relay key for deployer.globex.example.com? | A new key pair is created. Paste the new line on the host, test it, then remove the old line. The old key is used until the new one passes. | No | Rotate key |
| Revoke token | Revoke token "ci-runner"? | Anything using it stops working at once. | No | Revoke token |
| Delete real data now | Delete real data for run 3f9a21c0 now? | Deletes samples, the sandbox copies and raw lines in evidence; reports keep masked lines and numbers. Can't be undone. | Run ID | Delete real data |
| Kill switch | Stop all model calls? | Every running run pauses at its next model call. No data is lost. | No | Stop model calls |
| Disable user | Disable Avery? | Signs them out everywhere. Their approvals and history stay. | No | Disable user |

The customer list in "Approve deployment, shared" comes from the plan's impact results, never typed by hand.

## Empty states

Pattern: what this is, why it is empty, the next action (admin) or who to ask (viewer).

| Screen | Admin | Viewer |
| --- | --- | --- |
| Runs | No runs yet. A run turns sample logs into a tested add-on. [New run] | No runs yet. An admin starts runs. |
| Add-ons | No add-ons yet. An add-on appears here when you approve a run. [New run] | No add-ons yet. |
| Deployments | Nothing deployed yet. Deploy an approved add-on version to an environment. [Open Add-ons] | Nothing deployed yet. |
| Environments | No production environment yet. Your sandbox is ready; add the Splunk your add-ons should run on. [Add environment] | Only the sandbox is set up. |
| Discovery | No scans yet. A scan checks how well Splunk parses the data already in an index. [Scan index] | No scans yet. |
| Drift | No drift signals. Drift monitoring is off for every environment. [Turn it on in an environment] / or: No drift signals in the last 30 days. | Same, without the action |
| Needs you | Nothing needs you. | Nothing is waiting on an admin. |
| Filtered list | No deployments match these filters. [Clear filters] | Same |
