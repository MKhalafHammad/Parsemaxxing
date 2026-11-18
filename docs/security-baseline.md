# Parsemaxxing security baseline

> Written in Phase 11. One row per control, grouped by standard. The `appsec` agent owns the findings behind each row and every phase updates the rows it touches. Threats and residual risks are in [threat-model.md](threat-model.md); designs are in [design.md](design.md); phases are in [build-plan.md](build-plan.md). Last updated Nov 19, 2026.

## How to read this

- **Status:** **Built** means the control is in the code on `main` today and the named test proves it. **Partly built** says which part exists. **Planned** means not built yet; the Phase column says when it is due.
- **Where:** paths are under `engine/parsemaxxing/` unless they start with `web/`, `relay/`, `scripts/`, `.github/` or the repository root. Paths for planned controls name the package the design puts them in; they may not exist yet.
- **Tests:** paths are under `engine/tests/` unless they start with `web/` or `tests/`. "Adv." is `engine/tests/adversarial/test_adversarial.py`.
- **Release rule:** Phase 24 (release 2.0.0) needs every row **Built** with its test, or a residual risk in the threat model accepted in writing by the repository owner.
- Rows marked Built (Phase 12) or Built (Phase 13) are on those phase branches, in review, until they merge to `main`.
- Today's code has local accounts, roles, MFA and API tokens (Phase 13) but no LDAP. The platform must not be exposed beyond localhost before Phase 14 is built; `make up` refuses a non-loopback `HTTPS_BIND` without an explicit opt-in.

## OWASP Top 10:2025

| ID | Control | Where enforced | Test that proves it | Phase | Status | Owner agent |
| --- | --- | --- | --- | --- | --- | --- |
| A01-1 | Route policy registry: every route declares its role; deny by default | `auth/policy.py` (`check_routes`, `PUBLIC`), `api/app.py` (`create_app`) | `auth/test_auth.py::test_every_route_has_a_policy`, `test_a_route_without_a_policy_stops_the_build`, `test_a_public_route_cannot_also_carry_a_policy`, `test_anonymous_is_refused_before_the_body_is_read` | 13 | Built (Phase 13) | identity |
| A01-2 | Every route tested as anonymous, viewer and admin (BFLA) | `auth/`, `api/` | `auth/test_auth.py::test_every_route_as_anonymous_viewer_and_admin` | 13 | Built (Phase 13) | qa |
| A01-3 | Object checks on every id in a path (job, deployment, environment, customer, add-on version) (BOLA) | `api/`, `auth/` | `auth/test_auth.py::test_a_session_of_another_user_cannot_be_revoked`, `test_another_users_token_cannot_be_revoked_by_a_viewer`; `api/test_cli_api.py::test_rollback_checks_the_ta_and_version_exist_and_is_audited`; `api/test_api.py::test_bad_job_ids_and_unknown_runs` | 13, 17 | Partly built (Phase 13): job, user, session, API token and TA ids (and TA version on rollback); environment, customer and deployment ids planned (Phases 17, 18) | identity |
| A01-4 | CSRF: custom header `X-Parsemaxxing: 1` and Origin check on every state-changing request | `api/app.py` (middleware), `config.py` (`web_origins`), `web/proxy.ts`, `web/lib/hosts.ts` | `api/test_api.py::test_cross_site_requests_are_refused`; `auth/test_auth.py::test_csrf_is_refused_with_a_session`, `test_every_listed_web_origin_works_and_a_foreign_one_is_refused`; `test_config.py::test_web_origins`, `test_web_origins_refuses_wildcards_and_paths`; `tests/test_compose.py::test_engine_and_web_allow_the_same_origins`; `web/e2e/proxy.spec.ts` "cross-site state changes are refused" | 5, 6 (built); 13 (public origins) | Built (Phase 13): a cookie-bearing change needs `X-Parsemaxxing: 1` and an `Origin` in the `WEB_ORIGINS` list | identity |
| A01-5 | DNS rebinding: Host allowlist on engine and web, Origin from a fixed list | `api/app.py` (`TrustedHostMiddleware`), `web/proxy.ts` | `api/test_api.py::test_security_headers_cors_and_host_check`; `web/e2e/proxy.spec.ts` "DNS rebinding: an unknown Host is refused…" | 5, 6 | Built | frontend |
| A01-6 | SSRF-safe fetch helper (scheme allowlist, DNS resolved then private, loopback, link-local and metadata ranges refused, no redirect to another host, size and time caps) for URL import and outbound webhooks | shared fetch helper in `engine/parsemaxxing/` (location set in Phase 20 design) | SSRF tests: metadata IP, private ranges, DNS rebinding, cross-host redirect, oversize | 20 (URL import), 19 and 22 (outbound) | Planned | engine |
| A01-7 | Admin-set Splunk, LDAP and LLM URLs: admin-only, validated, audited | `environments/`, `auth/`, `llm/` | Validation and audit tests per URL type | 14, 16, 17 | Planned | engine |
| A01-8 | No interactive shell anywhere; relay accepts only fixed verbs | `relay/pmx-relay`, `deploy/` | Relay test refusing every verb outside its list | 18 | Planned | splunk |
| A02-1 | Security headers on API responses (`nosniff`, `X-Frame-Options: DENY`, `no-referrer`, `no-store`, CSP `default-src 'none'`, CORP) | `api/app.py` `SECURITY_HEADERS` | `api/test_api.py::test_security_headers_cors_and_host_check` | 5 | Built | engine |
| A02-2 | Web CSP with a per-request nonce and `strict-dynamic`, no `'unsafe-inline'` scripts; `frame-ancestors 'none'` | `web/proxy.ts` | `web/e2e/proxy.spec.ts` "pages and the API carry security headers, with a nonce…" | 6 | Built | frontend |
| A02-3 | CORS limited to the configured web origin | `api/app.py` (`CORSMiddleware`), `config.py` (`web_origins`) | `api/test_api.py::test_security_headers_cors_and_host_check`; `test_config.py::test_web_origins` | 5 | Built: the `WEB_ORIGINS` list from the environment (set by docker-compose); a setting in the UI planned (Phase 15) | engine |
| A02-4 | OpenAPI docs not exposed to non-admins | `api/app.py` (`docs_url`, `redoc_url`, `openapi_url` set to `None`) | None yet | 5; 13 (admin-only) | Built (stricter: off for everyone); admin-only docs and a test not done in Phase 13, still planned | engine |
| A02-5 | Secure defaults: TLS verify on, MFA on for local admins, debug off | `settings/`, `auth/`, `tools/splunk_client.py` | Default-value tests per setting | 12, 13 | Planned. Today TLS verify is off for the lab Splunk (`tools/splunk_client.py`, R2) | devops |
| A02-6 | Configuration health page listing every insecure toggle that is on | `settings/`, `web/` | Health page test with each toggle on | 15 | Planned | frontend |
| A03-1 | GitHub Actions pinned to commit SHAs | `.github/workflows/ci.yml` | semgrep `p/default` in `make security`; appsec review | 0 | Built | devops |
| A03-2 | Dependency audit: pip-audit, npm audit (shipped packages), bandit, semgrep, gitleaks in CI | `Makefile` `security`, `.github/workflows/ci.yml` | CI `make security` step | 0, 6 | Built (dev-dependency advisory tracked as R11) | devops |
| A03-3 | `npm ci` with the committed lockfile | `web/Dockerfile`, `web/package-lock.json` | Image build in CI | 6 | Built; `npm audit signatures` planned (Phase 12) | devops |
| A03-4 | Images pinned by digest (closes R12) | `docker-compose.yml`, `engine/Dockerfile`, `web/Dockerfile`, CI service images in `.github/workflows/ci.yml` | `tests/test_compose.py::test_every_image_is_pinned_by_digest` | 12 | Built | devops |
| A03-5 | Python dependencies locked with hashes (`--require-hashes`) | `engine/requirements.lock`, installed with `--require-hashes --no-deps` in `engine/Dockerfile` | `tests/test_compose.py::test_python_lock_covers_every_runtime_dependency`; the image build fails on a changed hash | 12 | Built | devops |
| A03-6 | CycloneDX SBOM per image and Trivy scan failing on high and critical | `.github/workflows/ci.yml` job `images`, `scripts/image_check.sh`, `make sbom` / `make scan` | CI job `images` | 12 | Built | devops |
| A03-7 | Two-week rule for new releases | dependency updates, appsec review | Review checklist | All | Built as a review rule (no automated check) | appsec |
| A03-8 | Embedding model files pinned by SHA-256; CIM add-on checksum checked | `knowledge/`, CIM library in `cim_spec/` or its v2 package | Tampered-file tests | 17c, 20 | Planned | knowledge |
| A04-1 | Vault: AES-256-GCM envelope encryption via `cryptography` only, per-secret data key, 96-bit random nonces, AAD binding id, purpose and version | `secrets/` | `secrets/test_vault.py` (round trip, tampered row, changed AAD fields, ciphertext moved to another row, wrong KEK, scope) | 12 | Built | identity |
| A04-2 | Argon2id password hashing at or above OWASP parameters | `auth/passwords.py` | None yet for the parameters; `auth/test_auth.py::test_unknown_user_and_wrong_password_take_the_same_time` covers the dummy verify | 13 | Built (Phase 13): `argon2-cffi` RFC 9106 low-memory profile (Argon2id, m=64 MiB, t=3, p=4); parameter test planned | identity |
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
| A07-1 | Local accounts: length 12 to 128, common-password list, lockout with backoff per account and IP, one generic error, constant-time compare | `auth/passwords.py`, `auth/service.py`, `auth/common_passwords.txt` | `auth/test_auth.py::test_password_rule`, `test_unknown_user_and_wrong_password_look_the_same`, `test_unknown_user_and_wrong_password_take_the_same_time`, `test_a_disabled_account_fails_like_a_wrong_password`, `test_lockout_after_repeated_failures_even_with_the_right_password`, `test_unknown_user_names_lock_too`, `test_per_ip_lockout_across_user_names`, `test_backoff_doubles_and_is_capped` | 13 | Built (Phase 13): 5 failures per user name, 20 per IP, 60 s doubling to 900 s. The common-password list is the project's own, 672 entries, smaller than a published top-10k list | identity |
| A07-2 | TOTP MFA with hashed recovery codes; required for local admins by default | `auth/` | `auth/test_auth.py::test_mfa_is_required_for_admins_and_replay_is_refused`, `test_mfa_requirement_can_be_turned_off`, `test_recovery_codes_are_single_use_and_hashed`, `test_mfa_failures_lock`, `test_the_totp_secret_is_in_the_vault_only`, `test_mfa_enrol_on_a_signed_in_session_needs_the_password` | 13 | Built (Phase 13): `pyotp`, ±1 step, replay guard, 10 single-use recovery codes. Reset MFA from the UI planned (Phase 15); `parsemaxxing admin reset` clears it today | identity |
| A07-3 | Sessions: hashed 256-bit ids, `__Host-pmx_session` flags, idle and absolute timeouts, rotation, revocation | `auth/` | `auth/test_auth.py::test_login_sets_a_hardened_cookie`, `test_session_fixation_the_id_rotates_at_login`, `test_expired_and_revoked_sessions_are_refused`, `test_logout_revokes_and_clears`, `test_password_change_revokes_every_other_session`, `test_role_change_signs_the_user_out_and_keeps_an_admin`, `test_an_open_event_stream_closes_once_its_credential_is_revoked` | 13 | Built (Phase 13): idle 30 min and absolute 12 h are settings. Idle-timeout warning banner planned (Phase 15, R25) | identity |
| A07-4 | API tokens: `pmxt_` prefix, hashed, expiry at most 90 days, role at most the creator's, revocable | `auth/` | `auth/test_auth.py::test_tokens_role_scoped_shown_once_and_hashed`, `test_role_escalation_through_token_creation_is_refused`, `test_a_demoted_owner_demotes_their_tokens`, `test_expired_and_revoked_tokens_are_refused`, `test_revoke_through_the_api_and_bad_tokens_are_throttled`, `test_disable_revokes_the_users_tokens`; `api/test_cli_api.py` (token file mode, never a command-line value) | 13 | Built (Phase 13): expiry 1 to 90 days; effective role the lower of the token's and the owner's; revoked on password change, role change, disable and admin reset | identity |
| A07-5 | First run: no default credentials, one-time setup token (60 min, single use) | `auth/` | `auth/test_auth.py::test_setup_token_is_single_use`, `test_an_expired_setup_token_is_refused`, `test_no_setup_token_once_an_admin_exists`, `test_engine_workers_share_one_setup_token`, `test_concurrent_setup_token_issue_agrees`, `test_force_reissues_the_setup_token` | 13 | Built (Phase 13): one token across engine workers; `make setup-token` issues a new one | identity |
| A08-1 | Append-only ledger, registry and events tables by trigger; app role cannot drop the triggers | `ledger/migrations/001`, `002`, `003`, `004` | `ledger/test_queue.py::test_ledger_is_append_only`, `::test_the_app_role_cannot_rewrite_or_unprotect_the_ledger`; `orchestrator/test_update.py::test_registry_versions_are_append_only_and_updates_need_the_current_version` | 5, 7 | Built; same triggers for `auth_events`, `settings_history`, `deployment_events` planned (12, 13, 18) | engine |
| A08-2 | Reproducible packages; install re-checks the hash | `ta_builder/`, `tools/splunk_client.py` | Adv. `test_packages_are_reproducible`; `tools/test_splunk_client.py::test_install_rechecks_hash_and_location` | 2, 4 | Built | engine |
| A08-3 | Deployment approvals bound to package SHA-256, environment and tiers | `deploy/` | Approval replay and mismatch tests | 18 | Planned | splunk |
| A08-4 | Only `deploy/` writes to a non-sandbox Splunk | `deploy/` | Test that finds any production write path outside `deploy/` | 18 | Planned | splunk |
| A08-5 | Ledger hash chain with `parsemaxxing ledger verify` and a UI integrity badge | `ledger/store.py`, `cli.py`, `ledger/backup.py`, `scripts/backup.sh`, `scripts/restore.sh` | `ledger/test_chain.py` (edits, removals, reorders, `test_cli_head_and_expect_head`, `test_expect_head_detects_a_recomputed_chain`); `ledger/test_backup.py::test_restore_verifies_the_ledger_against_the_recorded_head` | 12 | Partly built: chain, `ledger verify`, `ledger head` with `--expect-head`, and the head in each backup's `.sha256` file are built; the UI badge is planned. Someone who can rewrite both a backup and its sidecar is not detected unless the head is also kept off the server (R20) | engine |
| A08-6 | Write-once, content-addressed package store; hash checked on every read; no delete path for versions | `ta_store/` | Tampered store file test; no-delete grep and trigger test | 17b | Planned | engine |
| A08-7 | Relay verifies the package hash before staging | `relay/pmx-relay` | Wrong-hash relay test | 18 | Planned | splunk |
| A09-1 | Every run step, approval and promotion is a ledger row | `ledger/`, `orchestrator/` | `orchestrator/test_events.py`; `ledger/test_queue.py` | 5 | Built | engine |
| A09-2 | Audit events for login, failure, lockout, MFA, role, token, setting, secret, approval, deployment and rollback, with actor, time, client IP and outcome | `auth/`, `settings/`, `deploy/` | `auth/test_auth.py::test_auth_events_are_append_only_and_chained`, `test_no_credential_reaches_a_response_log_or_audit_row`; `api/test_cli_api.py::test_rollback_checks_the_ta_and_version_exist_and_is_audited` | 13 onward | Partly built (Phase 13): sign-in, failure, lockout, MFA, password, role, user, session, token, setup, run approve and reject, TA rollback and kill switch go to `auth_events` (hash-chained, checked by `ledger verify`); setting, secret and deployment events planned (15, 18) | identity |
| A09-3 | Optional forwarding to a `pmx_audit` index with alert templates (login failures, kill switch, integrity failures) | `analytics/` | Forwarding test on fixture data | 19 | Planned | engine |
| A10-1 | Fail closed in gate and Validator | `guardrails/`, `validator/` | `validator/test_validator_index_time.py::test_warning_check_fails_closed`, `::test_warning_check_error_fails_the_attempt`; Adv. `test_tampered_daily_total_fails_closed` | 2, 4 | Built; fail closed in auth and deploy planned (13, 18) | engine |
| A10-2 | Timeouts and bounded retries on every Splunk and model call; per-run wall clock | `agents/llm.py`, `tools/splunk_client.py`, `orchestrator/` | `agents/test_agents.py::test_malformed_output_is_retried_then_rejected`; `orchestrator/test_run.py` | 2, 4 | Built | engine |
| A10-3 | One error envelope (code, message, request id); no stack traces or internal paths to clients | `api/app.py`, `web/` proxy | `api/test_api.py::test_http_errors_use_the_envelope`, `::test_host_and_csrf_refusals_use_the_envelope`, `::test_body_limit_refusal_uses_the_envelope`, `::test_every_response_has_its_own_request_id`; `web/e2e/proxy.spec.ts` | 12 | Built (Phase 12). Server logs get only the exception type and the request id | engine |

## OWASP Top 10 for LLM Applications 2025

| ID | Control | Where enforced | Test that proves it | Phase | Status | Owner agent |
| --- | --- | --- | --- | --- | --- | --- |
| LLM01-1 | Logs, form fields, search results and human text passed as delimited data; tag-like text inside a block escaped | `agents/` | Adv. `test_injected_instruction_stays_inside_the_data_block`, `test_what_an_injected_model_would_propose_is_blocked`; `agents/test_agents.py::test_samples_are_delimited_data`, `::test_timezone_form_field_cannot_carry_instructions` | 2, 3 | Built | agents-ai |
| LLM01-2 | Injection fixtures for each new input path (discovery and drift samples, retrieved knowledge, imported docs) | `agents/`, `knowledge/` | Adversarial fixtures per path | 20, 21, 22 | Planned | qa |
| LLM02-1 | Masking at the LLM client for hosted providers | `masking/`, `llm/` | Property tests; test that a hosted call never carries a planted real value | 21 | Planned (R7) | agents-ai |
| LLM02-2 | Secret scan of samples before any model call | `masking/` | Planted-secret test | 21 | Planned | agents-ai |
| LLM02-3 | Egress policy per customer; fallback only when allowed | `llm/`, `orchestrator/` | Egress policy test | 16 | Planned | agents-ai |
| LLM02-4 | No credentials in prompts; API key redacted from probe output | `agents/`, `config.py` (`Settings.__repr__`), `tools/` probes | `tools/test_probes.py::test_failure_output_redacts_api_key` | 1, 2 | Built | agents-ai |
| LLM03-1 | Provider SDKs pinned (hash lock) | `engine/requirements.lock` | See A03-5 | 12 | Built | devops |
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
| LLM10-3 | Rate limits per user, token and IP | `api/`, `auth/` | Rate limit tests | 13 | Planned. Phase 13 built only the sign-in, MFA and bad-token throttles (A07-1); general request rate limits not done | identity |

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
| API1 BOLA | See A01-3 | `api/`, `auth/` | Per-object access tests | 13, 17 | Partly built (Phase 13); see A01-3 | identity |
| API2 Broken authentication | See A07-1 to A07-5 | `auth/` | See A07 | 13 | Built (Phase 13); LDAP planned (Phase 14) | identity |
| API3 Broken object property level authorization | `extra="forbid"` on every request body; response models never include secret fields | `api/app.py` models | `api/test_api.py::test_validation_logs_quote_client_chosen_field_names` (an extra field is refused); no-secret response test planned | 12, 13 | Partly built: JSON bodies forbid extra fields; no route returns a secret today, but there is no test for it yet (Phase 13) | engine |
| API4 Unrestricted resource consumption | Body caps before parsing (built); at most 20 event streams (built); pagination caps and rate limits (planned) | `api/app.py` | `api/test_api.py::test_request_bodies_are_capped_before_parsing` | 5; 13 | Partly built | engine |
| API5 BFLA | See A01-2 | `auth/` | `auth/test_auth.py::test_every_route_as_anonymous_viewer_and_admin` | 13 | Built (Phase 13) | identity |
| API6 Sensitive business flows | Approve and promote need the exact state (replay is a no-op); idempotent approve and deploy | `ledger/store.py`, `deploy/` | Adv. `test_replayed_approve_is_a_no_op`; `ledger/test_queue.py::test_db_refuses_a_skipped_transition` | 5; 18 | Built for builds; deployments planned | engine |
| API7 SSRF | See A01-6, A01-7 | fetch helper | See A01-6 | 16 to 22 | Planned | engine |
| API8 Security misconfiguration | See A02 | `api/app.py`, `web/proxy.ts` | See A02 | 5, 6, 12 | Partly built | devops |
| API9 Improper inventory management | Route inventory test; OpenAPI admin-only | `auth/`, `api/` | `auth/test_auth.py::test_every_route_has_a_policy`, `test_a_route_without_a_policy_stops_the_build` | 13 | Built (Phase 13): route inventory checked at startup and in tests; OpenAPI off for everyone | identity |
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
| SET-1 | Outside `config/bootstrap`, no code reads `os.environ` for runtime settings | `config.py` | `test_bootstrap.py::test_no_module_outside_bootstrap_reads_os_environ` | 12 | Built | engine |
| SET-2 | Old `PARSEWRIGHT_*` variables refused at start, naming the new name | `config.py` | `test_config.py::test_old_variable_in_the_environment_is_refused`, `::test_old_variable_in_the_env_file_is_refused` | 11 | Partly built: host CLI and engine refuse them; a Docker `.env` check in `init_env.py` is open | engine |
| SET-3 | Typed, bounded settings groups; versioned; every change in `settings_history` (secrets only "changed") | `settings/` | `settings/test_settings_service.py::test_bounds_and_unknown_fields_are_refused`, `::test_optimistic_version`, `::test_history_records_every_change_per_scope`, `::test_history_is_append_only_for_the_app_role` | 12 | Built | engine |
| SET-4 | Settings scoped platform, environment, client; reads take the scope explicitly; no "current environment" global | `settings/` | `settings/test_settings_service.py::test_inheritance_and_sources`, `::test_secret_fields_take_only_a_vault_id_of_the_same_scope`; `secrets/test_vault.py::test_a_secret_resolves_only_in_its_own_scope` | 12, 17 | Partly built: explicit scopes in the service; only the one v1 environment `lab` exists until Phase 17 | engine |
| SET-5 | Jobs read a settings snapshot at start and record its hash | `settings/`, `orchestrator/` | `settings/test_settings_service.py::test_snapshot_is_hash_addressed_and_frozen_in_time` | 12 | Partly built: the snapshot function exists; jobs do not use it yet (settings are read at process start) | engine |
| SET-6 | Export and import of non-secret settings only, validated and diffed | `settings/` | `settings/test_settings_service.py::test_export_never_contains_secrets_and_import_round_trips`, `::test_invalid_imports_are_refused_and_change_nothing` | 12 | Built (CLI and service; the UI is Phase 15) | engine |

## Secrets at rest and on the machine

| ID | Control | Where enforced | Test that proves it | Phase | Status | Owner agent |
| --- | --- | --- | --- | --- | --- | --- |
| SEC-1 | Vault design (A04-1); decryption only at the moment of use | `secrets/`, `config.py` (`Secrets.use`) | `secrets/test_vault.py` (see A04-1; `test_secret_value_never_in_logs_errors_or_history`) | 12 | Built. Long-lived clients (the `openai` and `splunk-sdk` clients) keep the token in memory for the life of the process | identity |
| SEC-2 | KEK file `secrets/pmx_kek`: 32 random bytes, mode 0400, git-ignored, Docker secret into the engine only | `scripts/make_secrets.py`, `secrets/` (`Kek.load`), `docker-compose.yml` | `tests/test_make_secrets.py::test_creates_every_secret_private_and_quiet`; `secrets/test_vault.py::test_kek_file_readable_by_group_or_others_is_refused`; `tests/test_compose.py::test_secrets_reach_only_the_services_that_need_them` (engine only; not web, not `migrate`) | 12 | Built | devops |
| SEC-3 | `rotate-kek` rewraps every data key | `secrets/`, `cli.py` | `secrets/test_vault.py::test_rotate_kek_round_trip`, `::test_rotate_kek_is_all_or_nothing`, `::test_rotate_kek_as_the_app_role`, `::test_cli_rotate_kek` | 12 | Built | identity |
| SEC-4 | Secrets never returned by the API; `repr` redaction on every model holding one | `secrets/`, `config.py`, `api/` | `secrets/test_vault.py::test_kek_repr_and_pickle_never_expose_the_key`; `tools/test_probes.py::test_failure_output_redacts_api_key` | 12, 13 | Partly built: `repr` redaction of the KEK, `Secrets` and `Settings` is built; there are no secret API routes yet (Phase 15 screens) | identity |
| SEC-5 | No secrets in container environment variables except bootstrap values; `/proc` exposure noted | `docker-compose.yml`, `config.py` | `tests/test_compose.py::test_secrets_reach_only_the_services_that_need_them` | 12 | Partly built: the database passwords and the KEK are files (Docker secrets). `LLM_API_KEY` and `SPLUNK_*_TOKEN` are still accepted as environment overrides, and then they win over the vault, so they are visible in `/proc` and `docker inspect` | devops |
| SEC-6 | `.env` written atomically with mode 0600; tokens never in process arguments or output | `scripts/env_set.py`, `scripts/init_env.py` | `tests/test_env_scripts.py::test_env_set_stores_tokens_quietly`, `::test_init_generates_placeholder_passwords_and_never_prints_them` | 10 | Built | devops |
| SEC-7 | Token expiry tracked; warnings at 14 and 3 days | `environments/`, `analytics/` | Expiry warning test | 17 | Planned (sandbox tokens expire after 7 days and are renewed on `make up` today) | splunk |

## Data integrity and confidentiality

| ID | Control | Where enforced | Test that proves it | Phase | Status | Owner agent |
| --- | --- | --- | --- | --- | --- | --- |
| DATA-1 | Ledger hash chain | `ledger/` | See A08-5 | 12 | Partly built (see A08-5) | engine |
| DATA-2 | Samples and masking maps encrypted at rest | `masking/`, intake | See A04-5 | 21 | Planned | engine |
| DATA-3 | Real logs deleted 30 days after the job ends at most (per client 0 to 30); purge job hourly and idempotent; reports rewritten with masked lines | purge job in `orchestrator/` or `masking/` | Planted-marker purge test over database and files | 21 | Planned | engine |
| DATA-4 | `pmx_` test index retention at most 30 days | `scripts/splunk_bootstrap.py` | Bootstrap test of `frozenTimePeriodInSecs` | 21 | Planned (the index is size-capped today, T5.3) | splunk |
| DATA-5 | Masked regression sets: stricter masking pass, checks must pass, secret scan must be clean | `ta_store/`, `masking/` | Regression set test | 17b, 21 | Planned | engine |
| DATA-6 | Uploads: single-file `.gz` only, decompressed size cap, UTF-8 text, no NUL, symlinks refused, fixed per-job names | `api/intake.py` | `api/test_api.py::test_upload_refusals`, `::test_nul_bytes_anywhere_are_refused`, `::test_symlinks_in_the_drop_folder_are_refused`, `::test_uploads_are_stored_under_fixed_per_job_names` | 5 | Built | engine |
| DATA-7 | Viewer views of raw production samples audited; "mask raw samples for viewers" setting | `api/`, `auth/` | Audit test | 13, 21 | Planned (R16) | identity |

## Database

| ID | Control | Where enforced | Test that proves it | Phase | Status | Owner agent |
| --- | --- | --- | --- | --- | --- | --- |
| DB-1 | Separate owner and app roles; the app role has no DDL and limited grants; owner credentials only in the one-shot `migrate` service | `ledger/migrations/002` to `006`, `docker-compose.yml` | `ledger/test_queue.py::test_the_app_role_cannot_rewrite_or_unprotect_the_ledger`; `ledger/test_migrations.py::test_fresh_database_gets_the_new_role_and_names`; `secrets/test_vault.py::test_app_role_cannot_move_a_secret_to_another_scope_or_delete_it`; `ledger/test_chain.py::test_app_role_appends_but_cannot_rewrite` | 5, 7, 11, 12 | Built | engine |
| DB-2 | `analytics_ro` role for read-only views | migrations, `analytics/` | Grant test | 19 | Planned | engine |
| DB-3 | `scram-sha-256` authentication | PostgreSQL config | Connection test with md5 refused | 12 | Planned (not checked in code today) | devops |
| DB-4 | TLS `verify-full` when PostgreSQL is not on the internal Docker network | `config.py` (DSN) | DSN test | 12 | Planned | devops |
| DB-5 | `statement_timeout` on the app role | migrations or DSN | Timeout test | 12 | Planned | engine |
| DB-6 | Encrypted backups (`pg_dump` to `age`) including the package store; restore tested in CI; retention at most 30 days advised | `ledger/backup.py`, `cli.py` `backup` / `restore`, `scripts/backup.sh`, `scripts/restore.sh`, `.github/workflows/ci.yml` job `restore-test` | `ledger/test_backup.py` (round trip, modes and 30-day pruning, checksum refusal, ledger head); `scripts/restore_test.sh` in CI | 12, 17b | Partly built: database backup with a `.sha256` sidecar, 30-day pruning, restore that refuses a missing or mismatched sidecar, and the CI round trip are built; the package store is not covered until Phase 17b | devops |
| DB-7 | Rename migration is safe to run twice; the v1 volumes are backed up before they are copied (005 itself takes no backup) | `ledger/migrations/005_rename_to_parsemaxxing.sql`, `scripts/migrate_v1_volumes.sh` | `ledger/test_migrations.py::test_005_is_safe_to_run_twice`; `tests/test_migrate_v1_volumes.py::test_non_empty_new_volume_is_never_overwritten` | 11 | Built | devops |
| DB-8 | A leftover `parsewright_app` role that cannot be dropped loses its login | `005_rename_to_parsemaxxing.sql` | `ledger/test_migrations.py` | 11 | Built | engine |
| BLD-1 | The repo-root build context exposes only `LICENSE` and `NOTICE` (root `.dockerignore`) | `.dockerignore`, `docker-compose.yml` | Manual build check in Phase 11; automated in Phase 12 | 11 | Built | devops |
| PRB-1 | Lab probe writes need `--lab-write`, touch only `__test_probe` apps, and `shc-push` needs the deployer's GUID | `tools/probes/` | `tools/test_lab_probes.py` | 11 | Built | splunk |
| DATA-9 | v1 volume backups (they hold real samples) are deleted within 30 days | `docs/setup.md`, `scripts/migrate_v1_volumes.sh` | None yet | 21 | Planned | devops |

## Docker

| ID | Control | Where enforced | Test that proves it | Phase | Status | Owner agent |
| --- | --- | --- | --- | --- | --- | --- |
| DK-1 | Non-root images | `engine/Dockerfile` (`USER parsemaxxing`), `web/Dockerfile` (`USER node`) | None automated; appsec review | 5, 6 | Built; automated check planned (12) | devops |
| DK-2 | `no-new-privileges`, `cap_drop: ALL`, read-only root filesystem for engine and web | `docker-compose.yml` | `tests/test_compose.py::test_hardening_and_limits_on_every_service` (every service except Splunk, R17) | 5, 6, 12 | Built | devops |
| DK-3 | No Docker socket in any container | `docker-compose.yml` | `tests/test_compose.py::test_hardening_and_limits_on_every_service` | 1, 12 | Built | devops |
| DK-4 | Published ports on `127.0.0.1` only; Splunk REST 8089 unpublished | `docker-compose.yml`, `scripts/up.sh` | `tests/test_compose.py::test_published_ports_are_loopback_and_postgres_is_not_published`; `tests/test_up_bind.py` | 5, 10, 12 | Built, with the `https` profile. `make up` refuses a non-loopback `HTTPS_BIND` unless `PMX_ALLOW_UNAUTHENTICATED_NETWORK=yes`, until login lands in Phase 13 | devops |
| DK-5 | Separate networks (Splunk cannot reach the engine API; database not reachable from web) | `docker-compose.yml` | `tests/test_compose.py::test_networks_separate_splunk_web_and_database` | 12 | Built (R10 narrowed) | devops |
| DK-6 | Secrets as files (Docker secrets); KEK never in the web container | `docker-compose.yml` | See SEC-2 | 12 | Built for the KEK and the database passwords; the LLM key and Splunk tokens can still come from the environment (SEC-5) | devops |
| DK-7 | CPU, memory and PID limits per container | `docker-compose.yml` | `tests/test_compose.py::test_hardening_and_limits_on_every_service` | 12 | Built | devops |

## Supply chain

| ID | Control | Where enforced | Test that proves it | Phase | Status | Owner agent |
| --- | --- | --- | --- | --- | --- | --- |
| SC-1 | Actions pinned by SHA; CI uses `pull_request` with `contents: read` and no secrets | `.github/workflows/ci.yml` | appsec review; semgrep | 0 | Built | devops |
| SC-2 | Images by digest; Python lock with hashes; SBOM; Trivy | see A03-4 to A03-6 | see A03 | 12 | Built (R12 closed) | devops |
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
