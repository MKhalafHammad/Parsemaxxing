"""The setting groups. Variable names are v1's: a v1 `.env` shows as "managed by environment".

Secret fields hold vault ids; v1 secret variables (LLM_API_KEY, SPLUNK_*_TOKEN) are imported into
the vault once and are not overrides.
"""

from pydantic import AnyHttpUrl

from parsemaxxing.settings.model import SecretRef, SettingsGroup, setting


class LlmSettings(SettingsGroup):
    GROUP = "llm"
    VERSION = 1
    base_url: AnyHttpUrl | None = setting(None, env="LLM_BASE_URL")
    model: str | None = setting(None, env="LLM_MODEL", min_length=1, max_length=200)
    api_key: SecretRef | None = setting(None, secret=True)
    run_token_ceiling: int = setting(
        300_000, env="PARSEMAXXING_RUN_TOKEN_CEILING", ge=1_000, le=10_000_000
    )


class SplunkSettings(SettingsGroup):
    GROUP = "splunk"
    VERSION = 1
    host: str | None = setting(
        None,
        scopes=("environment",),
        env="SPLUNK_HOST",
        min_length=1,
        max_length=253,
        pattern=r"^[A-Za-z0-9.:-]+$",
    )
    port: int = setting(8089, scopes=("platform", "environment"), env="SPLUNK_PORT", ge=1, le=65535)
    search_token: SecretRef | None = setting(None, scopes=("environment",), secret=True)
    deploy_token: SecretRef | None = setting(None, scopes=("environment",), secret=True)
    test_index: str = setting(
        "pmx_test",
        scopes=("platform", "environment", "client"),
        env="PARSEMAXXING_TEST_INDEX",
        pattern=r"^pmx_[a-z0-9_]{1,60}$",
    )


class IngestSettings(SettingsGroup):
    GROUP = "ingest"
    VERSION = 1
    job_ingest_mb: float = setting(20, env="PARSEMAXXING_JOB_INGEST_MB", gt=0, le=1_000)
    daily_ingest_mb: float = setting(500, env="PARSEMAXXING_DAILY_INGEST_MB", gt=0, le=100_000)


class RunSettings(SettingsGroup):
    """Worker tunables (were constants in orchestrator/worker.py and run.py)."""

    GROUP = "run"
    VERSION = 1
    daily_token_budget: int = setting(2_000_000, ge=1_000, le=1_000_000_000)
    llm_slots: int = setting(2, ge=1, le=64)  # model calls at once, across every worker
    max_attempts: int = setting(5, ge=1, le=20)  # attempts per stage


class BackupSettings(SettingsGroup):
    GROUP = "backup"
    VERSION = 1
    # The age public key backups are encrypted to; its private key is never on the server.
    age_recipient: str | None = setting(
        None, env="PARSEMAXXING_BACKUP_RECIPIENT", pattern=r"^age1[02-9ac-hj-np-z]{58}$"
    )
