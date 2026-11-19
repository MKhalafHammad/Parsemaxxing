# Features

What is built and what is planned. The README summarises this table. Built rows describe the code as it is; planned rows name the phase in [build-plan.md](build-plan.md) that builds them, and the design section in [design.md](design.md#v2-platform-design).

## v1 (built unless marked)

| Feature | Status |
| --- | --- |
| Repository foundation: CI, secret scanning, commit hooks | **Built** |
| One-command Docker stack (`make up`): Splunk, PostgreSQL, engine and UI; Splunk prepared automatically (test index, least-privilege roles and tokens, CIM add-on and macros) | **Built** (clean-VM test passed Nov 4) |
| Threat model and lab probes for the LLM API and Splunk ([docs/lab-findings.md](lab-findings.md)) | **Built** (all v1 lab questions, Q1 to Q11, answered) |
| Synthetic log generator with truth manifests (JSON, key=value, syslog, CSV) | **Built** |
| Profiler agent, with a human profile review in the UI (or skipped per run) | **Built** |
| Index-time agent with a retry loop fed by Validator evidence | **Built** |
| Extraction and CIM mapper agents with retry loops, regression re-runs and one backtrack | **Built** |
| Guardrails: stage gates plus a final gate over the whole package (allowlisted keys after Unicode normalisation, no forbidden keys, no foreign stanzas, eventtype anchoring, CIM provenance, environment-independent EVALs), with an adversarial suite of 87 tests | **Built** |
| Validator: index-time checks (event count, timestamp accuracy, fallback, parser warnings, `TIME_FORMAT` really matching every event) | **Built** |
| Validator: extraction and CIM checks (Authentication, Network_Traffic, Web) with the three-number CIM score | **Built** |
| Logs without a truth manifest: upload just the log. Generator samples are recognised and checked against their known answers; any other log is checked mechanically on every event (each time equal to the time written in its line, read by code; every value exactly as written in its line; CIM gaming rules), the run asks a human for the timezone only when the timestamps carry none, and the approval report lists the agents' decisions (timestamp reading, field meanings, value → CIM value with counts) | **Built** |
| TA builder: escaping conf writer, test identity, reproducible `.tgz` packaging with a file allowlist and SHA-256 | **Built** |
| Approval and promotion: `parsemaxxing approve <job> --sha256 …` (hash-bound, replay-safe), `parsemaxxing promote <job>` (deterministic rename to real names, both hashes linked, refuses existing TAs and sourcetypes, smoke test) | **Built** |
| CLI: `parsemaxxing run <file>` (all three stages) | **Built**. Since Phase 13 it goes through the API with an admin API token, so `parsemaxxing serve` (or the stack) must be running; `run --local` runs without API and database |
| Web UI (Next.js): runs board with "Needs you" and a new-run sheet; run workspace with a clickable, deep-linkable phase rail, every attempt's proposal, gate verdict and Splunk checks, and a live activity feed showing which agent is acting; profile review; approval report (raw vs parsed with field colours and a CIM view, readable config and row diffs, approve/reject, `.tgz` download); TA registry | **Built** |
| Parallel jobs: PostgreSQL queue (`FOR UPDATE SKIP LOCKED`, leases, heartbeats, crash resume), append-only ledger, worker pool with a global Splunk-write lock, LLM slots, daily token budget and kill switch | **Built** |
| HTTP API: upload (content checks, duplicates), runs, profile review, approve/reject, `.tgz` download, live server-sent events; `parsemaxxing serve` | **Built**. Every route needs a session or an API token since Phase 13; localhost only until Phase 14 |
| Routing for shared syslog feeds | Planned (Phase 23, replaces old Phase 9; design 7.11) |
| Parser updates: TA registry (versions, samples, baseline); `parsemaxxing update <TA> <file>` or the upload form; Diagnose with no model call (0 tokens if the TA already parses the new format); only failing stages patched; every attempt checked on the old and the new samples; diff against production and `local/` override flags in the review; in-place promotion with a version bump that keeps `local/`; exact-version `parsemaxxing rollback` | **Built** |
| Drift monitoring with automatic update jobs | Planned (Phase 22, replaces old Phase 8; design 7.10) |
| Drop folder intake (a watched folder, one job per subfolder) | Planned, no phase scheduled (the symlink-refusing intake helper is built) |
| Correcting a mapping from the approval report, sent back to the owning stage as evidence | Planned, no phase scheduled |
| Login with an approver role | **Built** in v2 Phase 13 as the `admin` role (in review); see the v2 table |
| Secret scan and masking of uploaded samples | Planned (Phase 21; use synthetic logs or on-prem mode until then) |
| A `pmx_audit` index and dashboard for agent activity | Planned (Phase 19) |
| Generated add-ons carry no PolyForm licence text (test in `engine/tests/ta_builder/`) | **Built** |

## v2 platform (planned unless marked)

| Feature | Design | Status |
| --- | --- | --- |
| Hardened Docker runtime: separate networks (Splunk reached only through a relay), Docker secrets for the KEK and database passwords, PostgreSQL unpublished unless the `cli` profile is on, resource limits, images pinned by digest, hashed Python lock, SBOM and Trivy scan in CI, optional HTTPS profile (Caddy, HSTS) | 7.7, 7.13 | **Built** (Phase 12, in review) |
| Settings service: typed, versioned settings with history, snapshots by hash, environment-variable overrides shown read-only, export and import with a diff; one-time `parsemaxxing settings import-env` of a v1 `.env` | 7.5 | **Built** (Phase 12, in review). Settings screens and the wizard listing removable `.env` keys planned (Phase 15); per-job snapshots planned (settings are read at process start) |
| Secrets vault: AES-256-GCM envelope encryption with a KEK from a Docker secret, `parsemaxxing secrets rotate-kek`; the LLM key and the Splunk tokens opened only at the moment of use; `LLM_API_KEY` and `SPLUNK_*_TOKEN`, when set, win over the vault | 7.5 | **Built** (Phase 12, in review). Expiry tracking planned (Phase 17) |
| Ledger hash chain with `parsemaxxing ledger verify`; `ledger head` and `verify --expect-head` check a head kept off the server; each backup records the head | 7.7 | **Built** (Phase 12, in review). UI integrity badge planned; keeping the head off the server is the admin's step |
| API errors in one envelope (code, message, request id), `X-Request-ID` on every response, no internals in messages | 7.7 | **Built** (Phase 12, in review) |
| Encrypted backups (`age`) with a restore tested in CI: `make backup` / `make restore`, `parsemaxxing backup` / `restore`; a `.sha256` file with the ledger head beside each, checked on restore; 30-day pruning | 7.5 | **Built** for the database (Phase 12, in review). The add-on package store planned (Phase 17b) |
| Local accounts (Argon2id), TOTP MFA, sessions, `viewer` and `admin` roles, API tokens, audit log, setup token at first run | 7.3 | **Built** (Phase 13, in review): lockout per user and per IP, MFA required for admins by default with 10 recovery codes, `__Host-pmx_session` with idle and absolute timeouts, `pmxt_` tokens (1 to 90 days), `make setup-token`, break-glass `parsemaxxing admin reset`, hash-chained `auth_events` and an audit log screen viewers can read; sign in, MFA, setup, account security, API tokens and users screens. The common-password list has 672 entries. Planned: Reset MFA and Unlock from the UI, the idle-timeout warning and an MFA QR code (Phase 15). `make up` still refuses exposure beyond localhost without an explicit opt-in |
| Every API route has a role in one policy registry (deny by default); CLI changes go through the API | 7.3 | **Built** (Phase 13, in review): checked at startup and in tests; `run`, `update`, `approve`, `reject`, `promote`, `rollback` and `kill` use the API with a token from `PARSEMAXXING_API_TOKEN` or `--token-file`; new admin route `POST /tas/{app}/rollback` (sandbox only) |
| LDAP login (LDAPS or StartTLS), group to role mapping, nested groups, break-glass local admin | 7.4 | **Built** (Phase 14, in review): only the uploaded CA bundle trusted, host name checked, TLS 1.2 minimum, ordered servers with failover; RFC 4515 filter escaping, exactly one entry, empty passwords refused before any connection; `member_of`, `member` (recursive) and `ad_nested` group modes (`ad_nested` tested against a mock only); highest mapped role, no mapped group means no access; optional MFA for directory users; Test connection and Test a user lookup on the Authentication and LDAP screen. Directory users cannot create API tokens. 23 tests against a real OpenLDAP in CI (`make ldap-test`) |
| App shell: navigation, context switcher, first-run setup wizard, settings, users, tokens and security-health screens, light and dark themes | 7.13 | Planned (Phase 15) |
| Any LLM provider (OpenAI-compatible, Azure OpenAI, Anthropic), chosen per agent, with a capability probe, egress policy and costs | 7.6 | Planned (Phase 16) |
| Customers and Splunk environments (dedicated or MSP shared), topology auto-discovery, connectivity tests, Splunk 10.2 and later | 7.1 | Planned (Phase 17) |
| Settings scoped per environment and per client, isolated from each other | 7.5 | Planned (Phase 17) |
| Add-on version control: every version kept, view files, download, compare any two versions, revert to any version without losing newer ones | 7.15 | Planned (Phase 17b) |
| CIM library: every data model of the CIM version installed in each environment | 7.16 | Planned (Phase 17c) |
| Automatic data model selection, bounded by code and proven by Splunk | 7.16 | Planned (Phase 17c) |
| Per-version Splunk spec keys checked by the gate | 7.12 | Planned (Phase 17c) |
| More log formats: syslog with payload, CEF, LEEF, XML, multi-line text and JSON, W3C, delimited, fixed-width, other encodings | 7.17 | Planned (Phase 17c) |
| Deployment to production per topology (standalone, SHC, heavy forwarders, deployment server for HFs), handoff or managed, with impact analysis, approval, verify and rollback | 7.2 | Planned (Phase 18) |
| Restricted SSH relay with fixed verbs and a read-only live console; command library with copy buttons | 7.2 | Planned (Phase 18) |
| Search-time preview on production events (read-only, never replaces the sandbox test) | 7.2 | Planned (Phase 18) |
| Analytics: runs, add-ons, deployments, cost, environments, knowledge | 7.8 | Planned (Phase 19) |
| Knowledge base (offline): Splunk spec files, Splunk agent skills, CIM definitions, project notes, imported manual PDFs and signed packs, reference add-ons, fix memory | 7.12 | Planned (Phase 20) |
| Discovery: find sourcetypes that need a parser and start a job from a finding (manual, read-only) | 7.9 | Planned (Phase 21) |
| Masking of production samples before any hosted model call | 7.10 | Planned (Phase 21) |
| Real logs deleted 30 days after the job ends (0 to 30 per client); masked regression sets kept with each version | 7.19 | Planned (Phase 21; regression sets in 17b) |
| Overlay add-ons that fix another add-on without editing it | 7.18 | Planned (Phase 21b) |
| Drift monitoring per environment, fix proposed as a deployment awaiting approval | 7.10 | Planned (Phase 22) |
| Mixed-feed routing placed on the parsing tier | 7.11 | Planned (Phase 23) |
| Security verification against OWASP Top 10:2025, LLM Top 10 2025 and Agentic Top 10 2026 | 7.7 | Planned (Phase 24) |
| Sourcetype naming and index routing governance | 7.14 | Planned (Phase 25, design only, no code) |
