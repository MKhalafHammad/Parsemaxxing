# engine/ conventions (Python)

Root rules in [../CLAUDE.md](../CLAUDE.md) apply. Design: [../docs/design.md](../docs/design.md). Rules marked "planned" are the rule to follow when that part lands; until then the current behaviour is described next to them.

## Language and tooling
- Python 3.12. Type hints on every public function.
- Ruff for lint and format (config in `pyproject.toml`, line length 100). Run `make lint`.
- pytest for tests in `engine/tests/`, mirroring the package layout (`tests/guardrails/test_*.py`).
- Plain Python, no agent framework (design decision). A new library needs a line in the design doc's tech stack table with the reason.

## Structure
- One package: `parsemaxxing`. Built modules: `api`, `orchestrator`, `agents`, `tools`, `guardrails`, `validator`, `ta_builder`, `ledger`, `cim_spec`, `generator`, `settings`, `secrets`; bootstrap is `config.py`. Planned: `auth`, `environments`, `deploy`, `discovery`, `drift`, `routing`, `knowledge`, `masking`, `analytics`, `llm`, `ta_store`.
- Pydantic models for every agent output, tool-call argument, API body and config object. Validate at the boundary; inside, trust the types.
- Never hardcode URLs, model names, tokens or passwords.

## Settings and secrets
- Bootstrap: `config.py` is the only module that reads `os.environ` (`tests/test_bootstrap.py` scans every module's AST; the `tools/probes/` lab scripts are exempt). Bootstrap values: the PostgreSQL connection (`POSTGRES_*`; `POSTGRES_PASSWORD_FILE` / `POSTGRES_APP_PASSWORD_FILE` win, both set and different is refused; `DATABASE_URL`, `MIGRATE_DATABASE_URL`), `PARSEMAXXING_KEK_FILE`, `PARSEMAXXING_PACKAGES_DIR`, `PARSEMAXXING_RUNS_DIR`, `WEB_ORIGIN`, `ALLOWED_HOSTS`, `PARSEMAXXING_LOG_LEVEL`. Other code calls `config` functions or reads `config.Settings`.
- Settings: runtime settings only through `SettingsService(conn, config.environ()).get(Group, scope)` (scope always explicit); the engine's `config.Settings` is built from the groups by `config.runtime()`. A variable named by a field (`setting(env=...)`) overrides it read-only. A new tunable is a field of a group in `settings/groups.py`, not a module constant.
- Secrets: only through the vault, `with vault.use(secret_id, scope) as p: p.text()` (sync), or `with settings.secrets.use(name) as value:` in engine code. Decrypted only inside that block (a long-lived client built from it, the OpenAI client or a splunk `Service`, keeps the token in memory for the process lifetime), never returned by the API, never in `repr`, exceptions, logs, the ledger or prompts. A secret's variable (`LLM_API_KEY`, `SPLUNK_SEARCH_TOKEN`, `SPLUNK_DEPLOY_TOKEN`), when set and non-empty, is a read-only override that wins over the vault, as for plain settings; otherwise the vault value is used (`parsemaxxing settings import-env` moves v1 values into the vault).

## API
- Built (Phase 12): errors use the one error envelope `{"error": {"code", "message", "request_id"}}` (plus `detail` for the v1 web UI) and every response has `X-Request-ID`; `HTTPException` messages are written for the client, never internals; unexpected errors return "internal error" and are logged with the request id.
- Phase 13, planned: every route declares its role in the route policy registry, as `Depends(require(Role.VIEWER))` or `Depends(require(Role.ADMIN))`. A route without a policy fails the route-inventory test. Details go to the audit log.
- Object-level checks on every id in a path (environment, customer, job, deployment, TA).

## Safety conventions
- SQL: parameterized queries only; state transitions as `UPDATE ... WHERE status = '<expected>'` and check the row count.
- Migrations: numbered SQL files in `ledger/migrations/` (`NNN_name.sql`, next free number), at most one per phase; never edit a merged one.
- Subprocess: argument lists, never `shell=True`.
- Paths: resolve and verify they stay inside the allowed root; never follow symlinks at intake.
- `.conf` files: only through the one escaping writer in `ta_builder`.
- Splunk: only through `tools` (search guard, scoped tokens); ingest targets must start with `pmx_`. Test deploys go only to sandboxes.
- Production Splunk (Phase 18, planned): written only from `deploy/`, and only with an approval naming the package SHA-256, environment and tiers.
- Customer searches (Phase 17, planned): built with the tenant base-search helper, restricted to that customer's indexes.
- Outbound fetches to admin-supplied URLs (planned): only through the SSRF-safe fetch helper; TLS verification on by default.
- LLM providers (Phase 16, planned): one adapter per provider kind in `llm/`; agents never know the provider. Masking happens in the LLM client, the one choke point, whenever the provider is hosted.
- Timeouts on every Splunk and model call.
- Logging: never log secrets, tokens or full prompts containing credentials; redact before writing to the ledger.
- Ledger: rows only through `Store.event`; the hash chain is computed by the migration 006 trigger; `parsemaxxing ledger verify` checks it.
- Untrusted text (logs, form fields, search results, retrieved knowledge) is passed to models as delimited data, never concatenated into instructions.
- Add-on versions are never deleted or rewritten; real logs are purged within 30 days of job end (design 7.15, 7.19).

## Tests
- Every new branch of logic has a test. Every guardrail has an adversarial test that tries to bypass it.
- Tests use only synthetic data from `parsemaxxing/generator/fixtures/`. Tests on `samples-local/` data are marked `local_only` and skipped in CI.
