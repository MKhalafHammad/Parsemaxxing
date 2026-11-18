"""Bootstrap: the only module that reads the process environment (design 7.5 "Bootstrap .env").

Bootstrap values: the PostgreSQL connection (passwords also as `*_FILE` Docker secrets), the KEK
file path, the filesystem layout (packages and runs folders), the API's allowed hosts and web
origin, the log level, and the backup recipient override. Everything else is a runtime setting
read through the settings service (`runtime()`), with secrets from the vault. The environment
is passed to the settings service, where a variable named by a field overrides it read-only.
A test (tests/test_bootstrap.py) fails if any other module reads os.environ.
"""

import os
import re
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote

ENV_KEYS = (
    # v1 runtime keys: still read as read-only overrides (secrets: transitional fallback) until
    # `parsemaxxing settings import-env` has moved them into settings and the vault.
    "LLM_API_KEY",
    "LLM_BASE_URL",
    "LLM_MODEL",
    "SPLUNK_HOST",
    "SPLUNK_PORT",
    "SPLUNK_SEARCH_TOKEN",
    "SPLUNK_DEPLOY_TOKEN",
    "PARSEMAXXING_TEST_INDEX",
    "PARSEMAXXING_RUN_TOKEN_CEILING",
    "PARSEMAXXING_JOB_INGEST_MB",
    "PARSEMAXXING_DAILY_INGEST_MB",
    # bootstrap keys
    "PARSEMAXXING_PACKAGES_DIR",
    "PARSEMAXXING_RUNS_DIR",
    "PARSEMAXXING_KEK_FILE",
    "PARSEMAXXING_LOG_LEVEL",
    "PARSEMAXXING_BACKUP_RECIPIENT",
    "DATABASE_URL",
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_PASSWORD_FILE",
    "POSTGRES_APP_PASSWORD",
    "POSTGRES_APP_PASSWORD_FILE",
    "MIGRATE_DATABASE_URL",
)
# v1 secret variables: used only while the vault field is unset (`settings import-env` moves
# them). Bootstrap-side so secret fields never get an environment override in the settings model.
# Variable names, not values.
LEGACY_SECRETS = {
    "llm_api_key": "LLM_API_KEY",
    "splunk_search_token": "SPLUNK_SEARCH_TOKEN",  # nosec B105
    "splunk_deploy_token": "SPLUNK_DEPLOY_TOKEN",  # nosec B105
}
# shortcut: v1 has exactly one Splunk environment; Phase 17 environments replace this name.
V1_ENVIRONMENT = "lab"
REPO = Path(__file__).resolve().parents[2]
KEY_LINE = re.compile(r"[A-Z][A-Z0-9_]*")
OLD_PREFIX, NEW_PREFIX = "PARSEWRIGHT_", "PARSEMAXXING_"
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")


def _refuse_old(key: str, where: str) -> None:
    """The rename has no fallback: an old variable would otherwise be silently ignored."""
    if key.startswith(OLD_PREFIX):
        new = NEW_PREFIX + key.removeprefix(OLD_PREFIX)
        raise RuntimeError(f"{key} ({where}) is no longer read; rename it to {new}")


def read_env_file(path: Path) -> dict[str, str]:
    """The known KEY=value lines of a .env file, never executed or expanded."""
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        key = key.strip()
        if sep:
            _refuse_old(key, str(path))
        if sep and key in ENV_KEYS and KEY_LINE.fullmatch(key):
            out[key] = value.strip()
    return out


def load_env_file(path: Path) -> None:
    """Export the known keys from a .env file without overriding the real environment.

    Every entry point calls this first, so it also refuses old PARSEWRIGHT_* names in the
    environment or the file.
    """
    for key in os.environ:
        _refuse_old(key, "environment")
    for key, value in read_env_file(path).items():
        os.environ.setdefault(key, value)


def environ() -> dict[str, str]:
    """A copy of the process environment, for the settings service's read-only overrides and
    for child processes (pg_dump, age)."""
    return dict(os.environ)


def kek_path() -> Path:
    from parsemaxxing.secrets import kek_file

    return kek_file(os.environ)


def log_level() -> str:
    level = os.environ.get("PARSEMAXXING_LOG_LEVEL", "INFO").upper()
    if level not in LOG_LEVELS:
        raise RuntimeError(f"PARSEMAXXING_LOG_LEVEL must be one of {', '.join(LOG_LEVELS)}")
    return level


def web_origin() -> str:
    return os.environ.get("WEB_ORIGIN", "http://localhost:3000")


def allowed_hosts() -> list[str]:
    hosts = os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1,engine").split(",")
    return [h.strip() for h in hosts if h.strip()]


def secret_env(name: str) -> str:
    """`NAME` or the file named by `NAME_FILE` (a Docker secret); the file wins. Both set with
    different values is refused: one of them is stale. Empty when neither is set."""
    value = os.environ.get(name, "")
    file = os.environ.get(f"{name}_FILE", "")
    if not file:
        return value
    try:
        from_file = Path(file).read_text(encoding="utf-8").strip()
    except OSError as e:
        raise RuntimeError(f"{name}_FILE cannot be read ({type(e).__name__})") from None
    if value and value != from_file:
        raise RuntimeError(f"{name} and {name}_FILE are both set and differ; remove {name}")
    return from_file


def app_password() -> str:
    return secret_env("POSTGRES_APP_PASSWORD")


def database_url(admin: bool = False) -> str:
    """The engine's connection: the limited parsemaxxing_app role when its password is set (it
    cannot alter or truncate the ledger); the owner account for migrations (admin=True).

    DATABASE_URL (app) and MIGRATE_DATABASE_URL (admin) override, as inside docker-compose.
    """
    override = os.environ.get("MIGRATE_DATABASE_URL" if admin else "DATABASE_URL")
    if override:
        return override
    app = app_password()
    if admin or not app:
        user, password = _require("POSTGRES_USER"), secret_env("POSTGRES_PASSWORD")
        if not password:
            raise RuntimeError("POSTGRES_PASSWORD (or POSTGRES_PASSWORD_FILE) is not set")
    else:
        user, password = "parsemaxxing_app", app
    host = os.environ.get("POSTGRES_HOST", "127.0.0.1")
    port = os.environ.get("POSTGRES_PORT", "55432")
    return (
        f"postgresql://{quote(user, safe='')}:{quote(password, safe='')}@{host}:{port}/"
        f"{quote(_require('POSTGRES_DB'), safe='')}"
    )


def _require(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise RuntimeError(f"{name} is not set (see .env.example)")
    return value


class Secrets:
    """Opens a runtime secret at the moment of use: the vault id held by a secret-typed setting,
    or, while that setting is unset, the v1 variable (transition; `settings import-env` ends it).
    Never holds a vault value outside `use`; redacted in `repr`, refuses pickling."""

    def __init__(
        self,
        refs: Mapping[str, tuple[Any, str]] | None = None,
        dsn: str = "",
        kek: Path | None = None,
        legacy: Mapping[str, str] | None = None,
    ):
        self._refs = dict(refs or {})  # name -> (Scope, vault id)
        self._dsn, self._kek_path, self._kek = dsn, kek, None
        self._legacy = dict(legacy or {})

    @classmethod
    def static(cls, **values: str) -> "Secrets":
        """Fixed values (tests, `run --local`)."""
        return cls(legacy=values)

    def source(self, name: str) -> str:
        return "vault" if name in self._refs else "environment" if name in self._legacy else ""

    @contextmanager
    def use(self, name: str) -> Iterator[str]:
        if name in self._refs:
            from parsemaxxing.ledger import store as db
            from parsemaxxing.secrets import Kek, Vault

            scope, secret_id = self._refs[name]
            if self._kek is None:
                self._kek = Kek.load(self._kek_path or kek_path())
            with db.connect(self._dsn) as conn, Vault(conn, self._kek).use(secret_id, scope) as p:
                yield p.text()
        elif name in self._legacy:
            yield self._legacy[name]
        else:
            var = LEGACY_SECRETS.get(name, name)
            raise RuntimeError(
                f"secret {name} is not set: store it in the vault "
                f"(`parsemaxxing settings import-env` imports {var} from a v1 .env)"
            )

    def __repr__(self) -> str:
        return f"Secrets({', '.join(f'{n}={self.source(n)}' for n in sorted(self.names()))})"

    def names(self) -> set[str]:
        return set(self._refs) | set(self._legacy)

    def __reduce__(self):
        raise TypeError("Secrets cannot be pickled")


@dataclass(frozen=True)
class Settings:
    """The runtime configuration one process works with, built by `runtime()` (or by tests)."""

    llm_base_url: str
    llm_model: str
    splunk_host: str
    splunk_port: int
    packages_dir: Path
    test_index: str
    run_token_ceiling: int
    runs_dir: Path = REPO / ".runs"
    job_ingest_mb: float = 20
    daily_ingest_mb: float = 500
    daily_tokens: int = 2_000_000
    llm_slots: int = 2
    max_attempts: int = 5
    dsn: str = ""
    secrets: Secrets = field(default_factory=Secrets, repr=False, compare=False)

    def __repr__(self) -> str:  # never print tokens, keys or the connection string
        return (
            f"Settings(model={self.llm_model!r}, splunk={self.splunk_host!r}, "
            f"index={self.test_index!r})"
        )


class _NoDatabase:
    """`run --local`: no PostgreSQL, so settings are defaults and environment variables only."""

    def execute(self, *_: Any, **__: Any) -> "_NoDatabase":
        return self

    def fetchone(self) -> None:
        return None


def runtime(local: bool = False) -> Settings:
    """Build the runtime Settings: groups from the settings service (platform scope, Splunk at
    the v1 environment), secrets as vault references, bootstrap paths from the environment."""
    from parsemaxxing.ledger import store as db
    from parsemaxxing.settings import (
        PLATFORM,
        IngestSettings,
        LlmSettings,
        RunSettings,
        Scope,
        SettingsService,
        SplunkSettings,
    )

    env = environ()
    dsn = "" if local else database_url()
    conn = _NoDatabase() if local else db.connect(dsn)
    try:
        svc = SettingsService(conn, env)  # type: ignore[arg-type]
        lab = Scope(V1_ENVIRONMENT)
        llm, splunk = svc.get(LlmSettings, PLATFORM), svc.get(SplunkSettings, lab)
        ingest, runs = svc.get(IngestSettings, PLATFORM), svc.get(RunSettings, PLATFORM)
    finally:
        if not local:
            conn.close()  # type: ignore[union-attr]
    refs = {
        name: (scope, ref)
        for name, scope, ref in (
            ("llm_api_key", PLATFORM, llm.api_key),
            ("splunk_search_token", lab, splunk.search_token),
            ("splunk_deploy_token", lab, splunk.deploy_token),
        )
        if ref
    }
    legacy = {n: env[v] for n, v in LEGACY_SECRETS.items() if n not in refs and env.get(v)}
    missing = [
        f"{label} ({var})"
        for label, var, value in (
            ("llm.base_url", "LLM_BASE_URL", llm.base_url),
            ("llm.model", "LLM_MODEL", llm.model),
            ("splunk.host", "SPLUNK_HOST", splunk.host),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(f"not set: {', '.join(missing)} (settings or environment)")
    return Settings(
        llm_base_url=str(llm.base_url),
        llm_model=str(llm.model),
        splunk_host=str(splunk.host),
        splunk_port=splunk.port,
        packages_dir=Path(_require("PARSEMAXXING_PACKAGES_DIR")),
        test_index=splunk.test_index,
        run_token_ceiling=llm.run_token_ceiling,
        runs_dir=Path(os.environ.get("PARSEMAXXING_RUNS_DIR") or REPO / ".runs"),
        job_ingest_mb=ingest.job_ingest_mb,
        daily_ingest_mb=ingest.daily_ingest_mb,
        daily_tokens=runs.daily_token_budget,
        llm_slots=runs.llm_slots,
        max_attempts=runs.max_attempts,
        dsn=dsn,
        secrets=Secrets(refs, dsn=dsn, kek=kek_path(), legacy=legacy),
    )


# --- one-time v1 .env import (`parsemaxxing settings import-env`) ---------------------------

# variable -> (group name, field, scope environment): plain values into settings
V1_PLAIN = {
    "LLM_BASE_URL": ("llm", "base_url", ""),
    "LLM_MODEL": ("llm", "model", ""),
    "PARSEMAXXING_RUN_TOKEN_CEILING": ("llm", "run_token_ceiling", ""),
    "SPLUNK_HOST": ("splunk", "host", V1_ENVIRONMENT),
    "SPLUNK_PORT": ("splunk", "port", V1_ENVIRONMENT),
    "PARSEMAXXING_TEST_INDEX": ("splunk", "test_index", V1_ENVIRONMENT),
    "PARSEMAXXING_JOB_INGEST_MB": ("ingest", "job_ingest_mb", ""),
    "PARSEMAXXING_DAILY_INGEST_MB": ("ingest", "daily_ingest_mb", ""),
}
# variable -> (group name, secret field, scope environment, vault name): secrets into the vault
V1_SECRETS = {
    "LLM_API_KEY": ("llm", "api_key", "", "llm.api_key"),
    "SPLUNK_SEARCH_TOKEN": ("splunk", "search_token", V1_ENVIRONMENT, "splunk.search_token"),
    "SPLUNK_DEPLOY_TOKEN": ("splunk", "deploy_token", V1_ENVIRONMENT, "splunk.deploy_token"),
}


def import_v1_env(
    conn: Any, values: Mapping[str, str], kek: Any, dry_run: bool, actor: str = "cli:import-env"
) -> tuple[list[str], list[str], bool]:
    """Move v1 .env values into settings (plain) and the vault (secrets). Idempotent: a value
    already stored is "unchanged". Returns (diff lines, variables now removable, ok). Secret
    values never appear in the lines; `kek` may be None only for a dry run."""
    import hmac

    from pydantic import ValidationError

    from parsemaxxing.secrets import Vault
    from parsemaxxing.settings import Scope, SettingsGroup, SettingsService

    # No overrides here: the import stores values so that the variables can then be removed.
    svc = SettingsService(conn, {})
    lines: list[str] = []
    removable: list[str] = []
    ok = True
    pending: dict[tuple[str, str], dict[str, Any]] = {}
    for var, (grp, fld, env) in V1_PLAIN.items():
        if not values.get(var):
            continue
        group, scope = SettingsGroup.registry[grp], Scope(env)
        where = f"{grp}.{fld} [{env or 'platform'}]"
        try:
            new = group.model_validate({fld: values[var]}).model_dump(mode="json")[fld]
        except ValidationError:
            lines.append(f"  ! {where}: {var} is not a valid value; not imported")
            ok = False
            continue
        old = svc.stored(group, scope)[0].get(fld)
        removable.append(var)
        if old == new:
            lines.append(f"  = {where}: unchanged")
            continue
        lines.append(f"  ~ {where}: {old!r} -> {new!r}")
        pending.setdefault((grp, env), {})[fld] = new
    if not dry_run:
        for (grp, env), vals in pending.items():
            svc.set(SettingsGroup.registry[grp], Scope(env), vals, actor)
    vault = Vault(conn, kek) if kek is not None else None
    for var, (grp, fld, env, name) in V1_SECRETS.items():
        value = values.get(var)
        if not value:
            continue
        group, scope = SettingsGroup.registry[grp], Scope(env)
        where = f"{grp}.{fld} [{env or 'platform'}]"
        ref = svc.stored(group, scope)[0].get(fld)
        if ref and vault is None:
            lines.append(f"  ? {where}: already set; not compared (no KEK in a dry run)")
            continue
        same = False
        if ref and vault is not None:
            with vault.use(ref, scope) as p:
                same = hmac.compare_digest(p.reveal(), value.encode("utf-8"))
        removable.append(var)
        if same:
            lines.append(f"  = {where}: secret unchanged")
            continue
        lines.append(f"  ~ {where}: secret {'replaced' if ref else 'set'} (value not shown)")
        if not dry_run and vault is not None:
            secret_id = vault.put(scope, name, value, actor)
            svc.set(group, scope, {fld: secret_id}, actor)
    return lines, removable, ok
