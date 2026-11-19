# settings

The settings service (design 7.5): typed, versioned setting groups per scope, with history, job snapshots, environment-variable overrides and export/import.

Status: built (Phase 12): `model.py` (scopes, group base, `setting()`), `groups.py` (`llm`, `splunk`, `ingest`, `run`, `backup`, `auth` (Phase 13), `ldap` (Phase 14)), `service.py`; tables `settings_groups`, `settings_history`, `settings_snapshots` in migration 006. Wired: bootstrap `config.runtime()` builds the engine's `config.Settings` from `llm`, `ingest`, `run` (platform) and `splunk` (environment `lab`, the one v1 environment until Phase 17), with secrets as vault references; `parsemaxxing settings import-env [--env-file .env] [--dry-run]` imports a v1 `.env` once (idempotent, shows a diff, lists the variables that can then be removed). Settings are read at process start (a change applies on restart); per-job snapshots by hash are planned. 001's `settings` table (kill switch) is separate.

## Interface

```python
from parsemaxxing.settings import PLATFORM, Scope, SettingsService, SplunkSettings

svc = SettingsService(conn, environ=os.environ)  # bootstrap passes the environment in
s = svc.get(SplunkSettings, Scope("lab"))  # frozen, validated model; scope is required
svc.explain(
    SplunkSettings, Scope("lab", "acme")
)  # {field: Effective(value, source, read_only, secret)}
svc.set(
    SplunkSettings,
    Scope("lab"),
    {"host": "splunk.example.com"},
    actor="admin",
    unset=("port",),
    expected_version=3,
)  # returns the new version; unset = reset to inherited
svc.history(Scope("lab"), "splunk")  # newest first, per scope and/or group
digest = svc.snapshot(Scope("lab"))  # SHA-256 of every group's effective values
svc.load_snapshot(digest)  # {group: model}; refuses an altered body
doc = svc.export(Scope("lab"))  # non-secret values set at that scope, JSON
svc.plan_import(doc, Scope("prod"))  # list[Change]: the diff, nothing written
svc.apply_import(doc, Scope("prod"), actor="admin")  # one transaction; also "clone"
```

## Rules

- **Scopes:** `PLATFORM`, `Scope(env)`, `Scope(env, client)`. Every read takes one; there is no current scope.
- **Resolution per field:** default < platform < environment < client < environment variable. A value counts only at a level listed in the field's `scopes`; `set` refuses other levels.
- **Environment variables:** a field declared with `env="NAME"` is overridden when the variable is present, reported as source `environment variable`, `read_only`, and refused by `set` and import.
- **Secrets:** secret fields (`setting(secret=True)`, type `SecretRef | None`) hold a vault id of exactly the same scope (checked on `set`). `explain` shows only whether set; history stores `redacted` with no value; export never contains them and import refuses them. A secret field may declare `env=` (`llm.api_key`: `LLM_API_KEY`, `splunk.search_token` / `deploy_token`: `SPLUNK_SEARCH_TOKEN` / `SPLUNK_DEPLOY_TOKEN`): when that variable is set and non-empty, `explain` reports source `environment variable`, `read_only`, and `set` refuses the field, but the service never reads the value (the resolved field stays the vault id); bootstrap (`config.Secrets`) uses the variable instead of the vault. An empty variable is not an override.
- **Versions:** each row has a change counter (`expected_version` for optimistic writes) and the group's `VERSION`. A row written by a newer group version is refused.
- **History:** `settings_history` is append-only by trigger, and the app role has only SELECT and INSERT; `settings_snapshots` likewise.
- **New group:** subclass `SettingsGroup`, set `GROUP` and `VERSION`, declare every field with `setting(...)` with bounds; bump `VERSION` on a change (renames and removals need an upgrade step in `SettingsService.stored`).
