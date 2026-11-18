# Parsemaxxing security baseline

> Written in Phase 11. One row per control, grouped by standard. The `appsec` agent owns the findings behind each row and every phase updates the rows it touches. Threats and residual risks are in [threat-model.md](threat-model.md); designs are in [design.md](design.md); phases are in [build-plan.md](build-plan.md). Last updated Nov 18, 2026.

## How to read this

- **Status:** **Built** means the control is in the code on `main` today and the named test proves it. **Partly built** says which part exists. **Planned** means not built yet; the Phase column says when it is due.
- **Where:** paths are under `engine/parsemaxxing/` unless they start with `web/`, `relay/`, `scripts/`, `.github/` or the repository root. Paths for planned controls name the package the design puts them in; they may not exist yet.
- **Tests:** paths are under `engine/tests/` unless they start with `web/` or `tests/`. "Adv." is `engine/tests/adversarial/test_adversarial.py`.
- **Release rule:** Phase 24 (release 2.0.0) needs every row **Built** with its test, or a residual risk in the threat model accepted in writing by the repository owner.
- Today's code is the v1 single-operator build (no login, localhost only). The platform must not be exposed beyond localhost before Phases 12 to 14 are built.

## OWASP Top 10:2025

| ID | Control | Where enforced | Test that proves it | Phase | Status | Owner agent |
| --- | --- | --- | --- | --- | --- | --- |
| A01-1 | Route policy registry: every route declares its role; deny by default | `auth/` (registry), `api/` | Route-inventory test that fails on any route without a policy | 13 | Planned | identity |
| A01-2 | Every route tested as anonymous, viewer and admin (BFLA) | `auth/`, `api/` | Role matrix test per route | 13 | Planned | qa |
| A01-3 | Object checks on every id in a path (job, deployment, environment, customer, add-on version) (BOLA) | `api/`, `auth/` | Per-object access tests | 13, 17 | Planned. Today only the shape of a job id is checked (`api/app.py` `JobId` pattern; `api/test_api.py::test_bad_job_ids_and_unknown_runs`) | identity |
| A01-4 | CSRF: custom header `X-Parsemaxxing: 1` and Origin check on every state-changing request | `api/app.py` (middleware), `web/proxy.ts` | `api/test_api.py::test_cross_site_requests_are_refused`; `web/e2e/proxy.spec.ts` "cross-site state changes are refused" | 5, 6 (built); 13 (public origins) | Built for localhost; check against configured public origins planned (Phase 13) | identity |
| A01-5 | DNS rebinding: Host allowlist on engine and web, Origin from a fixed list | `api/app.py` (`TrustedHostMiddleware`), `web/proxy.ts` | `api/test_api.py::test_security_headers_cors_and_host_check`; `web/e2e/proxy.spec.ts` "DNS rebinding: an unknown Host is refused…" | 5, 6 | Built | frontend |
| A01-6 | SSRF-safe fetch helper (scheme allowlist, DNS resolved then private, loopback, link-local and metadata ranges refused, no redirect to another host, size and time caps) for URL import and outbound webhooks | shared fetch helper in `engine/parsemaxxing/` (location set in Phase 20 design) | SSRF tests: metadata IP, private ranges, DNS rebinding, cross-host redirect, oversize | 20 (URL import), 19 and 22 (outbound) | Planned | engine |
| A01-7 | Admin-set Splunk, LDAP and LLM URLs: admin-only, validated, audited | `environments/`, `auth/`, `llm/` | Validation and audit tests per URL type | 14, 16, 17 | Planned | engine |
| A01-8 | No interactive shell anywhere; relay accepts only fixed verbs | `relay/pmx-relay`, `deploy/` | Relay test refusing every verb outside its list | 18 | Planned | splunk |
| A02-1 | Security headers on API responses (`nosniff`, `X-Frame-Options: DENY`, `no-referrer`, `no-store`, CSP `default-src 'none'`, CORP) | `api/app.py` `SECURITY_HEADERS` | `api/test_api.py::test_security_headers_cors_and_host_check` | 5 | Built | engine |
| A02-2 | Web CSP with a per-request nonce and `strict-dynamic`, no `'unsafe-inline'` scripts; `frame-ancestors 'none'` | `web/proxy.ts` | `web/e2e/proxy.spec.ts` "pages and the API carry security headers, with a nonce…" | 6 | Built | frontend |
| A02-3 | CORS limited to the configured web origin | `api/app.py` (`CORSMiddleware`) | `api/test_api.py::test_security_headers_cors_and_host_check` | 5 | Built (one origin from the environment); public-origin list from settings planned (Phase 12) | engine |
| A02-4 | OpenAPI docs not exposed to non-admins | `api/app.py` (`docs_url`, `redoc_url`, `openapi_url` set to `None`) | None yet | 5; 13 (admin-only) | Built (stricter: off for everyone); admin-only docs and a test planned (Phase 13) | engine |
| A02-5 | Secure defaults: TLS verify on, MFA on for local admins, debug off | `settings/`, `auth/`, `tools/splunk_client.py` | Default-value tests per setting | 12, 13 | Planned. Today TLS verify is off for the lab Splunk (`tools/splunk_client.py`, R2) | devops |
| A02-6 | Configuration health page listing every insecure toggle that is on | `settings/`, `web/` | Health page test with each toggle on | 15 | Planned | frontend |
| A03-1 | GitHub Actions pinned to commit SHAs | `.github/workflows/ci.yml` | semgrep `p/default` in `make security`; appsec review | 0 | Built | devops |
| A03-2 | Dependency audit: pip-audit, npm audit (shipped packages), bandit, semgrep, gitleaks in CI | `Makefile` `security`, `.github/workflows/ci.yml` | CI `make security` step | 0, 6 | Built (dev-dependency advisory tracked as R11) | devops |
| A03-3 | `npm ci` with the committed lockfile | `web/Dockerfile`, `web/package-lock.json` | Image build in CI | 6 | Built; `npm audit signatures` planned (Phase 12) | devops |
| A03-4 | Images pinned by digest (closes R12) | `docker-compose.yml`, `engine/Dockerfile`, `web/Dockerfile` | CI check that every `image:` and `FROM` has a digest | 12 | Planned (tags only today, R12) | devops |
| A03-5 | Python dependencies locked with hashes (`--require-hashes`) | engine lock file, `engine/Dockerfile` | Image build fails on a changed hash | 12 | Planned (`pyproject.toml` uses `>=` ranges today) | devops |
| A03-6 | CycloneDX SBOM per image and Trivy scan failing on high and critical | `.github/workflows/ci.yml`, `make sbom` | CI job | 12 | Planned | devops |
| A03-7 | Two-week rule for new releases | dependency updates, appsec review | Review checklist | All | Built as a review rule (no automated check) | appsec |
| A03-8 | Embedding model files pinned by SHA-256; CIM add-on checksum checked | `knowledge/`, CIM library in `cim_spec/` or its v2 package | Tampered-file tests | 17c, 20 | Planned | knowledge |
| A04-1 | Vault: AES-256-GCM envelope encryption via `cryptography` only, per-secret data key, 96-bit random nonces, AAD binding id, purpose and version | `secrets/` | Round-trip, tampered-ciphertext and moved-ciphertext tests | 12 | Planned | identity |
| A04-2 | Argon2id password hashing at or above OWASP parameters | `auth/` | Parameter test; hash format test | 13 | Planned | identity |
| A04-3 | TLS 1.2 or later everywhere; certificates verified | `tools/splunk_client.py`, `llm/`, `auth/` (LDAP), fetch helper | TLS tests against a self-signed endpoint without its CA | 12, 14, 17 | Planned (R2) | devops |
| A04-4 | No secrets in URLs except the Splunk drift webhook token (Splunk cannot send headers), which also checks source IP | `api/` webhook route, `drift/` | Webhook test: wrong token, wrong IP | 22 | Planned | engine |
| A04-5 | Samples and masking maps encrypted at rest | `masking/`, intake in `api/intake.py` | Test that stored sample bytes are not plaintext | 21 | Planned | engine |
| A05-1 | Parameterized SQL only | `ledger/store.py` | bandit and semgrep in `make security`; code review | 5 | Built | engine |
| A05-2 | No `shell=True`; subprocesses with argument lists | `cli.py` (the only subprocess use) | bandit B602/B603 in `make security` | 2, 5 | Built | engine |
| A05-3 | One escaping `.conf` writer: values with newlines or a trailing backslash rejected; stanza names checked | `ta_builder/` | Adv. `test_newline_injection_cannot_add_a_stanza`; `ta_builder/test_ta_builder.py::test_writer_rejects_*` | 2 | Built | engine |
| A05-4 | SPL: code-owned base search, command allowlist, subsearches and macros refused; Validator identifiers allowlisted | `tools/` search guard, `validator/` | Adv. `test_forbidden_search_commands`; `tools/test_search_guard_and_regex.py` | 3 | Built for the test index; tenant base search planned (A05-5) | splunk |
| A05-5 | Tenant base search restricted to the customer's index allowlist | `discovery/`, `drift/`, `deploy/` (preview) | Out-of-allowlist and SPL-escape adversarial tests | 17, 21 | Planned | splunk |
| A05-6 | LDAP filter escaping per RFC 4515 | `auth/` | Filter-injection test against OpenLDAP in CI | 14 | Planned | identity |
| A05-7 | `defusedxml` for any XML the engine parses | format detection and validator (7.17) | XXE and entity-expansion fixtures | 17c | Planned (the engine parses no XML today) | splunk |
| A05-8 | Safe tar handling: no traversal, links or oversized members | `orchestrator/` (kept packages), `api/intake.py` (uploads), `ta_store/`, CIM library, `knowledge/`, `relay/` | `orchestrator/test_update.py::test_a_kept_package_with_anything_outside_the_ta_is_refused`; `api/test_api.py::test_upload_refusals` (archives refused) | 4, 5, 7; 17b, 17c, 18, 20 | Partly built: kept packages and uploads; CIM, spec, pack, store and relay extraction planned | engine |
| A05-9 | UI renders log and model text only as React text; lint bans `dangerouslySetInnerHTML` and other HTML sinks | `web/` components, `web/eslint.config.mjs` | `web/e2e/xss.spec.ts`; `make lint` | 6 | Built | frontend |
| A05-10 | Relay arguments validated (app name pattern, version, hash, server class); no shell | `relay/pmx-relay` | Relay injection tests | 18 | Planned | splunk |
| A06-1 | Threat model v2 before code; abuse cases written per phase | `docs/threat-model.md`, build-plan "Appsec review focus" | appsec review per phase | 11 onward | Partly built: threat model v2 written in Phase 11 (awaiting owner review); per-phase abuse cases planned | appsec |
| A06-2 | Human approval bound to the package SHA-256 before promotion | `orchestrator/promote.py`, `api/app.py` | Adv. `test_approval_needs_the_exact_hash`, `test_one_changed_byte_after_approval_blocks_promotion` | 4 | Built for builds; deployment approvals planned (A08-3) | engine |
| A06-3 | Testing only on sandboxes; test identity; `pmx_` ingest targets only | `tools/splunk_client.py`, `orchestrator/` | Adv. `test_ingest_outside_pmx_is_refused`, `test_rename_restores_real_names_only`; `tools/test_splunk_client.py::test_ingest_refuses_non_pmx_indexes` | 2, 4 | Built (v1 has only a sandbox); production separation planned (A08-4) | splunk |
| A07-1 | Local accounts: length 12 to 128, common-password list, lockout with backoff per account and IP, one generic error, constant-time compare | `auth/` | Brute-force, lockout and enumeration tests | 13 | Planned | identity |
| A07-2 | TOTP MFA with hashed recovery codes; required for local admins by default | `auth/` | MFA enrolment, replay and recovery tests | 13 | Planned | identity |
| A07-3 | Sessions: hashed 256-bit ids, `__Host-pmx_session` flags, idle and absolute timeouts, rotation, revocation | `auth/` | Session tests (fixation, rotation, revocation, timeouts) | 13 | Planned | identity |
| A07-4 | API tokens: `pmxt_` prefix, hashed, expiry at most 90 days, role at most the creator's, revocable | `auth/` | Token tests | 13 | Planned | identity |
| A07-5 | First run: no default credentials, one-time setup token (60 min, single use) | `auth/` | Setup token expiry and reuse tests | 13 | Planned | identity |
| A08-1 | Append-only ledger, registry and events tables by trigger; app role cannot drop the triggers | `ledger/migrations/001`, `002`, `003`, `004` | `ledger/test_queue.py::test_ledger_is_append_only`, `::test_the_app_role_cannot_rewrite_or_unprotect_the_ledger`; `orchestrator/test_update.py::test_registry_versions_are_append_only_and_updates_need_the_current_version` | 5, 7 | Built; same triggers for `auth_events`, `settings_history`, `deployment_events` planned (12, 13, 18) | engine |
| A08-2 | Reproducible packages; install re-checks the hash | `ta_builder/`, `tools/splunk_client.py` | Adv. `test_packages_are_reproducible`; `tools/test_splunk_client.py::test_install_rechecks_hash_and_location` | 2, 4 | Built | engine |
| A08-3 | Deployment approvals bound to package SHA-256, environment and tiers | `deploy/` | Approval replay and mismatch tests | 18 | Planned | splunk |
| A08-4 | Only `deploy/` writes to a non-sandbox Splunk | `deploy/` | Test that finds any production write path outside `deploy/` | 18 | Planned | splunk |
| A08-5 | Ledger hash chain with `parsemaxxing ledger verify` and a UI integrity badge | `ledger/` | Chain tamper test | 12 | Planned | engine |
| A08-6 | Write-once, content-addressed package store; hash checked on every read; no delete path for versions | `ta_store/` | Tampered store file test; no-delete grep and trigger test | 17b | Planned | engine |
| A08-7 | Relay verifies the package hash before staging | `relay/pmx-relay` | Wrong-hash relay test | 18 | Planned | splunk |
| A09-1 | Every run step, approval and promotion is a ledger row | `ledger/`, `orchestrator/` | `orchestrator/test_events.py`; `ledger/test_queue.py` | 5 | Built | engine |
| A09-2 | Audit events for login, failure, lockout, MFA, role, token, setting, secret, approval, deployment and rollback, with actor, time, client IP and outcome | `auth/`, `settings/`, `deploy/` | Audit event test per action | 13 onward | Planned | identity |
| A09-3 | Optional forwarding to a `pmx_audit` index with alert templates (login failures, kill switch, integrity failures) | `analytics/` | Forwarding test on fixture data | 19 | Planned | engine |
| A10-1 | Fail closed in gate and Validator | `guardrails/`, `validator/` | `validator/test_validator_index_time.py::test_warning_check_fails_closed`, `::test_warning_check_error_fails_the_attempt`; Adv. `test_tampered_daily_total_fails_closed` | 2, 4 | Built; fail closed in auth and deploy planned (13, 18) | engine |
| A10-2 | Timeouts and bounded retries on every Splunk and model call; per-run wall clock | `agents/llm.py`, `tools/splunk_client.py`, `orchestrator/` | `agents/test_agents.py::test_malformed_output_is_retried_then_rejected`; `orchestrator/test_run.py` | 2, 4 | Built | engine |
| A10-3 | One error envelope (code, message, request id); no stack traces or internal paths to clients | `api/` | Error envelope test per failure branch | 13 | Planned | engine |

## OWASP Top 10 for LLM Applications 2025

| ID | Control | Where enforced | Test that proves it | Phase | Status | Owner agent |
| --- | --- | --- | --- | --- | --- | --- |
| LLM01-1 | Logs, form fields, search results and human text passed as delimited data; tag-like text inside a block escaped | `agents/` | Adv. `test_injected_instruction_stays_inside_the_data_block`, `test_what_an_injected_model_would_propose_is_blocked`; `agents/test_agents.py::test_samples_are_delimited_data`, `::test_timezone_form_field_cannot_carry_instructions` | 2, 3 | Built | agents-ai |
| LLM01-2 | Injection fixtures for each new input path (discovery and drift samples, retrieved knowledge, imported docs) | `agents/`, `knowledge/` | Adversarial fixtures per path | 20, 21, 22 | Planned | qa |
| LLM02-1 | Masking at the LLM client for hosted providers | `masking/`, `llm/` | Property tests; test that a hosted call never carries a planted real value | 21 | Planned (R7) | agents-ai |
| LLM02-2 | Secret scan of samples before any model call | `masking/` | Planted-secret test | 21 | Planned | agents-ai |
| LLM02-3 | Egress policy per customer; fallback only when allowed | `llm/`, `orchestrator/` | Egress policy test | 16 | Planned | agents-ai |
| LLM02-4 | No credentials in prompts; API key redacted from probe output | `agents/`, `config.py` (`Settings.__repr__`), `tools/` probes | `tools/test_probes.py::test_failure_output_redacts_api_key` | 1, 2 | Built | agents-ai |
| LLM03-1 | Provider SDKs pinned (hash lock) | engine lock file | Image build with `--require-hashes` | 12 | Planned (`>=` ranges today) | devops |
| LLM03-2 | Provider and model recorded per call in the ledger | `llm/`, `ledger/` | Ledger content test | 16 | Planned | agents-ai |
| LLM04-1 | Knowledge trust tiers; imported docs quarantined until an admin approves; content hashes; re-index on change | `knowledge/` | Poisoning test: an imported doc with instructions changes nothing the gate allows | 20 | Planned | knowledge |
| LLM05-1 | Strict schema output: every object closed, every property required | `agents/llm.py` (`strict_schema`) | `agents/test_agents.py::test_malformed_output_is_retried_then_rejected` | 2 | Built | agents-ai |
| LLM05-2 | Allowlisted keys with typed values and bounds; one escaping writer; output never executed or rendered as HTML | `guardrails/`, `ta_builder/`, `web/` | `guardrails/test_gate_index_time.py::test_unknown_keys_are_blocked`, `::test_bad_values_are_blocked`; `web/e2e/xss.spec.ts` | 2, 4, 6 | Built | engine |
| LLM06-1 | Agents call no tools and never deploy or see tokens | `agents/`, `orchestrator/` | Agents return schema objects only (`agents/test_agents.py`); tokens never passed to agents | 2 | Built | agents-ai |
| LLM06-2 | The Drift Analyst's single masked `fetch_more_samples` tool | `drift/` | Tool argument schema and masking tests | 22 | Planned | agents-ai |
| LLM06-3 | Production writes need human approval | `deploy/` | See A08-3 | 18 | Planned | splunk |
| LLM07-1 | Prompts are public in the repo and contain no secrets, customer names or internal details | `agents/` | gitleaks in pre-commit and CI; appsec review | 2 | Built | appsec |
| LLM08-1 | Local embeddings and storage; no customer log data in the knowledge base; tier and source filters in code; chunk provenance per run | `knowledge/` | Retrieval filter tests; test that no sample text is indexed | 20 | Planned | knowledge |
| LLM09-1 | Splunk judges every proposal; only the Validator moves a run forward | `validator/`, `orchestrator/` | Adv. suite; `orchestrator/test_run.py::test_fix_loop_feeds_evidence_back` | 2, 3 | Built | engine |
| LLM09-2 | References shown in the approval report; knowledge never overrides a failing check | `knowledge/`, `orchestrator/` | Report test | 20 | Planned | knowledge |
| LLM10-1 | Per-run token ceiling, LLM concurrency cap, daily budget, kill switch | `agents/llm.py`, `ledger/`, `api/app.py` | `ledger/test_queue.py::test_kill_switch_and_daily_tokens`; `api/test_api.py::test_kill_switch_endpoint` | 2, 5 | Built for one provider; cost caps across providers planned (16) | agents-ai |
| LLM10-2 | Upload and request size limits; line-length cap | `api/app.py` (`BodyLimit`), `api/intake.py` | `api/test_api.py::test_request_bodies_are_capped_before_parsing`, `::test_long_lines_and_oversized_estimates_are_refused` | 5 | Built | engine |
| LLM10-3 | Rate limits per user, token and IP | `api/`, `auth/` | Rate limit tests | 13 | Planned | identity |

## OWASP Top 10 for Agentic Applications 2026

| ID | Control | Where enforced | Test that proves it | Phase | Status | Owner agent |
| --- | --- | --- | --- | --- | --- | --- |
| ASI01 Goal hijack | Data, not instruction, on every input path; the gate and the Validator decide | `agents/`, `guardrails/`, `validator/` | See LLM01-1 and LLM01-2 | 2, 4; 20 to 22 | Built for v1 inputs; new paths planned | agents-ai |
| ASI02 Tool misuse | Agents have no tools; searches are code-owned; no interactive shell | `agents/`, `tools/`, `relay/` | See LLM06-1, A05-4, A01-8 | 2, 3; 18 | Built for v1; relay planned | agents-ai |
| ASI03 Identity and privilege abuse | Agents hold no credentials; per-purpose Splunk accounts (search, deploy, read) | `orchestrator/`, `scripts/splunk_bootstrap.py`, `environments/` | `tests/test_splunk_bootstrap.py::test_roles_hold_exactly_the_capabilities_they_need` | 1, 2; 17 | Built for the sandbox; production accounts planned | splunk |
| ASI04 Agentic supply chain | Pinned SDKs; prompts in the repo; pinned `splunk-agent-skills` commit reviewed like code | engine lock, `agents/`, `third_party/` | See A03-5, LLM03-1 | 12, 20 | Planned (prompts in repo: built) | devops |
| ASI05 Unexpected code execution | No code execution from model output; package file allowlist; no scripted inputs, `bin/` or external lookups | `ta_builder/`, `guardrails/` | `ta_builder/test_ta_builder.py::test_package_refuses_files_off_the_allowlist`; Adv. `test_conf_files_outside_the_allowlist` | 2, 4 | Built | engine |
| ASI06 Memory and context poisoning | Fresh context per agent; knowledge tiers and quarantine; fix memory never offers a rejected fix | `agents/`, `knowledge/` | See LLM04-1; fix memory test | 2; 20 | Built for fresh context; knowledge planned | knowledge |
| ASI07 Insecure inter-agent communication | Agents never talk to each other; the orchestrator passes only validated objects | `orchestrator/` | `orchestrator/test_run.py` | 2 | Built | agents-ai |
| ASI08 Cascading failures | Budgets, backtrack once, fail closed, per-tier verify and stop on failure | `orchestrator/`, `deploy/` | See A10-1, LLM10-1; rollout stop test | 4; 18 | Built for runs; deployments planned | engine |
| ASI09 Human-agent trust exploitation | Approval report shows evidence, not model claims; confirmation names the hash; high-risk flags | `orchestrator/report.py`, `web/` | `orchestrator/test_report.py`; `web/e2e/flow.spec.ts` | 6; 18 | Built for builds; high-risk deployment flags planned | frontend |
| ASI10 Rogue agents | Ledger of every proposal; kill switch | `ledger/`, `api/app.py` | See A09-1, LLM10-1 | 5 | Built | engine |

## OWASP API Security Top 10 2023

| ID | Control | Where enforced | Test that proves it | Phase | Status | Owner agent |
| --- | --- | --- | --- | --- | --- | --- |
| API1 BOLA | See A01-3 | `api/`, `auth/` | Per-object access tests | 13, 17 | Planned | identity |
| API2 Broken authentication | See A07-1 to A07-5 | `auth/` | See A07 | 13 | Planned | identity |
| API3 Broken object property level authorization | `extra="forbid"` on every request body; response models never include secret fields | `api/` models | Test that unknown fields are refused and no response carries a secret | 12, 13 | Planned (bodies today are form fields with length caps) | engine |
| API4 Unrestricted resource consumption | Body caps before parsing (built); at most 20 event streams (built); pagination caps and rate limits (planned) | `api/app.py` | `api/test_api.py::test_request_bodies_are_capped_before_parsing` | 5; 13 | Partly built | engine |
| API5 BFLA | See A01-2 | `auth/` | Role matrix test | 13 | Planned | identity |
| API6 Sensitive business flows | Approve and promote need the exact state (replay is a no-op); idempotent approve and deploy | `ledger/store.py`, `deploy/` | Adv. `test_replayed_approve_is_a_no_op`; `ledger/test_queue.py::test_db_refuses_a_skipped_transition` | 5; 18 | Built for builds; deployments planned | engine |
| API7 SSRF | See A01-6, A01-7 | fetch helper | See A01-6 | 16 to 22 | Planned | engine |
| API8 Security misconfiguration | See A02 | `api/app.py`, `web/proxy.ts` | See A02 | 5, 6, 12 | Partly built | devops |
| API9 Improper inventory management | Route inventory test; OpenAPI admin-only | `auth/`, `api/` | Route-inventory test | 13 | Planned (OpenAPI off today) | identity |
| API10 Unsafe consumption of APIs | Splunk, LDAP and provider responses treated as data, schema-validated or summarised by code | `agents/llm.py`, `validator/`, `tools/` | `validator/test_validator_index_time.py::test_raw_splunkd_lines_never_reach_the_agent`; `agents/test_agents.py::test_malformed_output_is_retried_then_rejected` | 2, 3 | Built for Splunk and the model; LDAP planned (14) | engine |

## LDAP

| ID | Control | Where enforced | Test that proves it | Phase | Status | Owner agent |
| --- | --- | --- | --- | --- | --- | --- |
| LDAP-1 | LDAPS or StartTLS only, plain refused; CA bundle and hostname checked | `auth/` | OpenLDAP-in-CI tests | 14 | Planned | identity |
| LDAP-2 | Filter escaping (RFC 4515); exactly one entry or fail | `auth/` | Filter-injection test | 14 | Planned | identity |
| LDAP-3 | Empty password refused before any bind | `auth/` | Unauthenticated-bind test | 14 | Planned | identity |
| LDAP-4 | Groups mapped at every login; no mapped group means no access; nested groups supported | `auth/` | No-group denial and nested-group tests | 14 | Planned | identity |
| LDAP-5 | Bind password in the vault, never logged; generic user errors | `auth/`, `secrets/` | Log scan test | 14 | Planned | identity |
| LDAP-6 | Ordered servers with failover; local break-glass admin | `auth/` | Failover test; LDAP-down login test | 14 | Planned | identity |

## Settings and configuration

| ID | Control | Where enforced | Test that proves it | Phase | Status | Owner agent |
| --- | --- | --- | --- | --- | --- | --- |
| SET-1 | Outside `config/bootstrap`, no code reads `os.environ` for runtime settings | `settings/`, bootstrap module | Test that fails on any other `os.environ` read | 12 | Planned (`api/app.py` and `config.py` read the environment today) | engine |
| SET-2 | Old `PARSEWRIGHT_*` variables refused at start, naming the new name | `config.py` | `test_config.py::test_old_variable_in_the_environment_is_refused`, `::test_old_variable_in_the_env_file_is_refused` | 11 | Partly built: host CLI and engine refuse them; a Docker `.env` check in `init_env.py` is open | engine |
| SET-3 | Typed, bounded settings groups; versioned; every change in `settings_history` (secrets only "changed") | `settings/` | Validation and history tests | 12 | Planned | engine |
| SET-4 | Settings scoped platform, environment, client; reads take the scope explicitly; no "current environment" global | `settings/` | Cross-environment isolation test | 12, 17 | Planned | engine |
| SET-5 | Jobs read a settings snapshot at start and record its hash | `settings/`, `orchestrator/` | Snapshot test | 12 | Planned | engine |
| SET-6 | Export and import of non-secret settings only, validated and diffed | `settings/` | Test that an export contains no secret | 12 | Planned | engine |

## Secrets at rest and on the machine

| ID | Control | Where enforced | Test that proves it | Phase | Status | Owner agent |
| --- | --- | --- | --- | --- | --- | --- |
| SEC-1 | Vault design (A04-1); decryption only at the moment of use | `secrets/` | See A04-1 | 12 | Planned | identity |
| SEC-2 | KEK file `secrets/pmx_kek`: 32 random bytes, mode 0400, git-ignored, Docker secret into the engine only | `Makefile` `setup`/`secrets`, `docker-compose.yml` | Test of file mode and that the web container has no KEK mount | 12 | Planned | devops |
| SEC-3 | `rotate-kek` rewraps every data key | `secrets/`, `cli.py` | Rotation test | 12 | Planned | identity |
| SEC-4 | Secrets never returned by the API; `repr` redaction on every model holding one | `secrets/`, `api/` | API and `repr` tests | 12, 13 | Partly built: `Settings.__repr__` redacts today (`tools/test_probes.py::test_failure_output_redacts_api_key`) | identity |
| SEC-5 | No secrets in container environment variables except bootstrap values; `/proc` exposure noted | `docker-compose.yml`, bootstrap | Compose check | 12 | Planned (tokens are in `.env` today) | devops |
| SEC-6 | `.env` written atomically with mode 0600; tokens never in process arguments or output | `scripts/env_set.py`, `scripts/init_env.py` | `tests/test_env_scripts.py::test_env_set_stores_tokens_quietly`, `::test_init_generates_placeholder_passwords_and_never_prints_them` | 10 | Built | devops |
| SEC-7 | Token expiry tracked; warnings at 14 and 3 days | `environments/`, `analytics/` | Expiry warning test | 17 | Planned (sandbox tokens expire after 7 days and are renewed on `make up` today) | splunk |

## Data integrity and confidentiality

| ID | Control | Where enforced | Test that proves it | Phase | Status | Owner agent |
| --- | --- | --- | --- | --- | --- | --- |
| DATA-1 | Ledger hash chain | `ledger/` | See A08-5 | 12 | Planned | engine |
| DATA-2 | Samples and masking maps encrypted at rest | `masking/`, intake | See A04-5 | 21 | Planned | engine |
| DATA-3 | Real logs deleted 30 days after the job ends at most (per client 0 to 30); purge job hourly and idempotent; reports rewritten with masked lines | purge job in `orchestrator/` or `masking/` | Planted-marker purge test over database and files | 21 | Planned | engine |
| DATA-4 | `pmx_` test index retention at most 30 days | `scripts/splunk_bootstrap.py` | Bootstrap test of `frozenTimePeriodInSecs` | 21 | Planned (the index is size-capped today, T5.3) | splunk |
| DATA-5 | Masked regression sets: stricter masking pass, checks must pass, secret scan must be clean | `ta_store/`, `masking/` | Regression set test | 17b, 21 | Planned | engine |
| DATA-6 | Uploads: single-file `.gz` only, decompressed size cap, UTF-8 text, no NUL, symlinks refused, fixed per-job names | `api/intake.py` | `api/test_api.py::test_upload_refusals`, `::test_nul_bytes_anywhere_are_refused`, `::test_symlinks_in_the_drop_folder_are_refused`, `::test_uploads_are_stored_under_fixed_per_job_names` | 5 | Built | engine |
| DATA-7 | Viewer views of raw production samples audited; "mask raw samples for viewers" setting | `api/`, `auth/` | Audit test | 13, 21 | Planned (R16) | identity |

## Database

| ID | Control | Where enforced | Test that proves it | Phase | Status | Owner agent |
| --- | --- | --- | --- | --- | --- | --- |
| DB-1 | Separate owner and app roles; the app role has no DDL and limited grants; owner credentials only in the one-shot `migrate` service | `ledger/migrations/002`, `003`, `004`, `docker-compose.yml` | `ledger/test_queue.py::test_the_app_role_cannot_rewrite_or_unprotect_the_ledger`; `ledger/test_migrations.py::test_fresh_database_gets_the_new_role_and_names` | 5, 7, 11 | Built | engine |
| DB-2 | `analytics_ro` role for read-only views | migrations, `analytics/` | Grant test | 19 | Planned | engine |
| DB-3 | `scram-sha-256` authentication | PostgreSQL config | Connection test with md5 refused | 12 | Planned (not checked in code today) | devops |
| DB-4 | TLS `verify-full` when PostgreSQL is not on the internal Docker network | `config.py` (DSN) | DSN test | 12 | Planned | devops |
| DB-5 | `statement_timeout` on the app role | migrations or DSN | Timeout test | 12 | Planned | engine |
| DB-6 | Encrypted backups (`pg_dump` to `age`) including the package store; restore tested in CI; retention at most 30 days advised | `cli.py` `backup`, `.github/workflows/ci.yml`, `docs/setup.md` | Restore test in CI | 12, 17b | Planned | devops |
| DB-7 | Rename migration is safe to run twice; the v1 volumes are backed up before they are copied (005 itself takes no backup) | `ledger/migrations/005_rename_to_parsemaxxing.sql`, `scripts/migrate_v1_volumes.sh` | `ledger/test_migrations.py::test_005_is_safe_to_run_twice`; `tests/test_migrate_v1_volumes.py::test_non_empty_new_volume_is_never_overwritten` | 11 | Built | devops |
| DB-8 | A leftover `parsewright_app` role that cannot be dropped loses its login | `005_rename_to_parsemaxxing.sql` | `ledger/test_migrations.py` | 11 | Built | engine |
| BLD-1 | The repo-root build context exposes only `LICENSE` and `NOTICE` (root `.dockerignore`) | `.dockerignore`, `docker-compose.yml` | Manual build check in Phase 11; automated in Phase 12 | 11 | Built | devops |
| PRB-1 | Lab probe writes need `--lab-write`, touch only `__test_probe` apps, and `shc-push` needs the deployer's GUID | `tools/probes/` | `tools/test_lab_probes.py` | 11 | Built | splunk |
| DATA-9 | v1 volume backups (they hold real samples) are deleted within 30 days | `docs/setup.md`, `scripts/migrate_v1_volumes.sh` | None yet | 21 | Planned | devops |

## Docker

| ID | Control | Where enforced | Test that proves it | Phase | Status | Owner agent |
| --- | --- | --- | --- | --- | --- | --- |
| DK-1 | Non-root images | `engine/Dockerfile` (`USER parsemaxxing`), `web/Dockerfile` (`USER node`) | None automated; appsec review | 5, 6 | Built; automated check planned (12) | devops |
| DK-2 | `no-new-privileges`, `cap_drop: ALL`, read-only root filesystem for engine and web | `docker-compose.yml` | None automated; appsec review (`docker compose config`) | 5, 6 | Built; automated check planned (12) | devops |
| DK-3 | No Docker socket in any container | `docker-compose.yml` | None automated; appsec review | 1 | Built; automated check planned (12) | devops |
| DK-4 | Published ports on `127.0.0.1` only; Splunk REST 8089 unpublished | `docker-compose.yml` | None automated; appsec review | 5, 10 | Built; HTTPS profile with a reverse proxy planned (12) | devops |
| DK-5 | Separate networks (Splunk cannot reach the engine API; database not reachable from web) | `docker-compose.yml` | Compose network test | 12 | Planned (R10) | devops |
| DK-6 | Secrets as files (Docker secrets); KEK never in the web container | `docker-compose.yml` | See SEC-2 | 12 | Planned | devops |
| DK-7 | CPU, memory and PID limits per container | `docker-compose.yml` | Compose check | 12 | Planned | devops |

## Supply chain

| ID | Control | Where enforced | Test that proves it | Phase | Status | Owner agent |
| --- | --- | --- | --- | --- | --- | --- |
| SC-1 | Actions pinned by SHA; CI uses `pull_request` with `contents: read` and no secrets | `.github/workflows/ci.yml` | appsec review; semgrep | 0 | Built | devops |
| SC-2 | Images by digest; Python lock with hashes; SBOM; Trivy | see A03-4 to A03-6 | see A03 | 12 | Planned (R12) | devops |
| SC-3 | Third-party content keeps its licence: `splunk-agent-skills` pinned with its `LICENSE` and listed in `THIRD_PARTY_NOTICES.md` | `third_party/`, `THIRD_PARTY_NOTICES.md` | Licence file check | 20 | Planned | knowledge |
| SC-4 | No Splunk documentation or licensed Splunk files in the repo | repository | appsec review; parser tests use files written for the tests | 11 onward | Built as a review rule | appsec |
| SC-5 | Relay package verified against its `SHA256SUMS` on install | `relay/` | Relay install test | 18 | Planned | devops |

## Public repository exposure

| ID | Control | Where enforced | Test that proves it | Phase | Status | Owner agent |
| --- | --- | --- | --- | --- | --- | --- |
| PUB-1 | gitleaks in pre-commit and over the full history in CI | `.pre-commit-config.yaml`, `Makefile` `security`, `.github/workflows/ci.yml` | CI `make lint` and `make security` | 0 | Built | appsec |
| PUB-2 | Commit-msg hook rejects attribution trailers and assistant names | `scripts/check_commit_msg.py`, `.pre-commit-config.yaml` | `tests/test_check_commit_msg.py::test_rejects_attribution` | 0 | Built | devops |
| PUB-3 | Only synthetic logs in the repo; documentation IP ranges, `example.com` and placeholder names (Acme, Globex, Initech) | `engine/parsemaxxing/generator/fixtures/`, every doc | appsec review per PR | All | Built as a review rule | appsec |
| PUB-4 | `samples-local/` git-ignored and blocked by a pre-commit and a CI check on the path and on content hashes; `local_only` tests skipped in CI | `.gitignore`, `.pre-commit-config.yaml`, `.github/workflows/ci.yml` | Hook test with a planted file | 12 | Planned (not in `.gitignore` or the hooks today) | devops |
| PUB-5 | Vulnerability reports through GitHub private vulnerability reporting; no project email address | `SECURITY.md` | Owner setting | 11 | Built in the doc; the repository setting is an owner action | docs |
