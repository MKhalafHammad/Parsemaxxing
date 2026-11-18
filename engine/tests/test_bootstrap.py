"""Bootstrap boundary (design 7.5): only config.py reads the environment; runtime settings come
from the settings service and secrets from the vault; the one-time v1 .env import."""

import ast
import base64
import os
import pickle
from pathlib import Path

import pytest

from parsemaxxing import config
from parsemaxxing.cli import main as cli_main
from parsemaxxing.secrets import Kek, Vault
from parsemaxxing.settings import (
    PLATFORM,
    LlmSettings,
    RunSettings,
    Scope,
    SettingsService,
    SplunkSettings,
)

PACKAGE = Path(config.__file__).parent
BOOTSTRAP = {PACKAGE / "config.py"}
# Lab probes are standalone scripts run by hand against a lab node (docs/lab-findings.md), not
# runtime code: they read their tokens from the environment on purpose.
EXEMPT_DIRS = {PACKAGE / "tools" / "probes"}
LAB = Scope("lab")
TOKEN = "synthetic-token-value-91c2e4"  # noqa: S105  # synthetic, not a credential
KEY = "synthetic-llm-key-55aa"  # gitleaks:allow


def _reads_environment(tree: ast.AST) -> list[int]:
    """Lines that read the process environment: os.environ / os.getenv (any alias of os or
    posix), or importing environ / getenv from them."""
    modules = {"os", "posix"}
    aliases = {
        a.asname or a.name
        for n in ast.walk(tree)
        if isinstance(n, ast.Import)
        for a in n.names
        if a.name in modules
    }
    lines = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and node.attr in ("environ", "environb", "getenv", "getenvb")
            and isinstance(node.value, ast.Name)
            and node.value.id in aliases
        ):
            lines.append(node.lineno)
        elif isinstance(node, ast.ImportFrom) and node.module in modules:
            if {a.name for a in node.names} & {"environ", "environb", "getenv", "getenvb"}:
                lines.append(node.lineno)
    return lines


def test_no_module_outside_bootstrap_reads_os_environ():
    offenders = []
    for path in sorted(PACKAGE.rglob("*.py")):
        if path in BOOTSTRAP or any(d in path.parents for d in EXEMPT_DIRS):
            continue
        for line in _reads_environment(ast.parse(path.read_text(encoding="utf-8"))):
            offenders.append(f"{path.relative_to(PACKAGE)}:{line}")
    assert offenders == [], f"read the environment only in config.py: {offenders}"


@pytest.mark.parametrize(
    "src",
    [
        "import os\nos.environ['X']",
        "import os\nos.getenv('X')",
        "from os import environ\nenviron.get('X')",
        "from os import getenv as g\ng('X')",
        "import posix\nposix.environ",
        "import os as o\no.environ.get('X')",
    ],
)
def test_the_scan_catches_every_spelling(src):
    assert _reads_environment(ast.parse(src))


# --- database passwords: X or X_FILE ------------------------------------------------------


def _db_env(monkeypatch, **values):
    for k in ("DATABASE_URL", "MIGRATE_DATABASE_URL", "POSTGRES_PASSWORD", "POSTGRES_APP_PASSWORD"):
        monkeypatch.delenv(k, raising=False)
        monkeypatch.delenv(f"{k}_FILE", raising=False)
    monkeypatch.setenv("POSTGRES_USER", "owner")
    monkeypatch.setenv("POSTGRES_DB", "pmx")
    for k, v in values.items():
        monkeypatch.setenv(k, v)


def test_password_files_are_read_and_win(tmp_path, monkeypatch):
    (tmp_path / "pw").write_text("from-file\n")
    (tmp_path / "app").write_text("app-from-file\n")
    _db_env(
        monkeypatch,
        POSTGRES_PASSWORD_FILE=str(tmp_path / "pw"),
        POSTGRES_APP_PASSWORD_FILE=str(tmp_path / "app"),
    )
    assert ":from-file@" in config.database_url(admin=True)
    assert config.database_url().startswith("postgresql://parsemaxxing_app:app-from-file@")
    _db_env(monkeypatch, POSTGRES_PASSWORD="plain")
    assert ":plain@" in config.database_url(admin=True)


def test_password_and_file_that_differ_are_refused(tmp_path, monkeypatch):
    (tmp_path / "pw").write_text("from-file\n")
    _db_env(monkeypatch, POSTGRES_PASSWORD="other", POSTGRES_PASSWORD_FILE=str(tmp_path / "pw"))
    with pytest.raises(RuntimeError, match="both set and differ") as err:
        config.database_url(admin=True)
    assert "other" not in str(err.value) and "from-file" not in str(err.value)
    _db_env(monkeypatch, POSTGRES_PASSWORD="from-file", POSTGRES_PASSWORD_FILE=str(tmp_path / "pw"))
    assert ":from-file@" in config.database_url(admin=True)  # same value: fine
    _db_env(monkeypatch, POSTGRES_PASSWORD_FILE=str(tmp_path / "missing"))
    with pytest.raises(RuntimeError, match="cannot be read"):
        config.database_url(admin=True)


def test_log_level_is_checked(monkeypatch):
    monkeypatch.setenv("PARSEMAXXING_LOG_LEVEL", "debug")
    assert config.log_level() == "DEBUG"
    monkeypatch.setenv("PARSEMAXXING_LOG_LEVEL", "LOUD")
    with pytest.raises(RuntimeError):
        config.log_level()


def test_kek_file_variable_is_a_known_env_key():
    assert "PARSEMAXXING_KEK_FILE" in config.ENV_KEYS


# --- runtime settings from the store and the vault ----------------------------------------


@pytest.fixture
def store_env(pg, pg_dsn, tmp_path, monkeypatch):
    """A clean settings store and vault, a KEK file, and no v1 runtime variables."""
    conn = pg.conn
    with conn.transaction():
        conn.execute("ALTER TABLE settings_history DISABLE TRIGGER settings_history_no_truncate")
        conn.execute("TRUNCATE secrets, vault_kek, settings_history, settings_groups")
        conn.execute("ALTER TABLE settings_history ENABLE TRIGGER settings_history_no_truncate")
    kek = tmp_path / "kek"
    kek.write_bytes(base64.b64encode(os.urandom(32)) + b"\n")
    kek.chmod(0o400)
    for var in (*config.V1_PLAIN, *config.V1_SECRETS, "MIGRATE_DATABASE_URL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("DATABASE_URL", pg_dsn)
    monkeypatch.setenv("PARSEMAXXING_KEK_FILE", str(kek))
    monkeypatch.setenv("PARSEMAXXING_PACKAGES_DIR", str(tmp_path / "pkgs"))
    return conn, Kek.load(kek)


def _configure(conn, kek):
    svc = SettingsService(conn, {})
    svc.set(LlmSettings, PLATFORM, {"base_url": "https://llm.example.com/v1", "model": "m"}, "t")
    vault = Vault(conn, kek)
    key = vault.put(PLATFORM, "llm.api_key", KEY, "t")
    svc.set(LlmSettings, PLATFORM, {"api_key": key}, "t")
    tok = vault.put(LAB, "splunk.search_token", TOKEN, "t")
    svc.set(SplunkSettings, LAB, {"host": "splunk.example.com", "search_token": tok}, "t")
    svc.set(RunSettings, PLATFORM, {"llm_slots": 3, "max_attempts": 2}, "t")


def test_runtime_reads_settings_and_opens_secrets_only_on_use(store_env, monkeypatch):
    conn, kek = store_env
    _configure(conn, kek)
    s = config.runtime()
    assert (s.llm_model, s.splunk_host) == ("m", "splunk.example.com")
    assert (s.llm_slots, s.max_attempts) == (3, 2)
    assert s.daily_tokens == 2_000_000 and s.test_index == "pmx_test"
    for text in (repr(s), repr(s.secrets), str(s)):
        assert TOKEN not in text and KEY not in text and "postgresql" not in text
    with pytest.raises(TypeError):
        pickle.dumps(s.secrets)
    with s.secrets.use("splunk_search_token") as value:
        assert value == TOKEN
    with s.secrets.use("llm_api_key") as value:
        assert value == KEY
    with pytest.raises(RuntimeError, match="splunk_deploy_token is not set") as err:
        with s.secrets.use("splunk_deploy_token"):
            pass
    assert "import-env" in str(err.value)


def test_environment_variable_overrides_a_stored_setting(store_env, monkeypatch):
    conn, kek = store_env
    _configure(conn, kek)
    monkeypatch.setenv("LLM_MODEL", "from-env")
    assert config.runtime().llm_model == "from-env"


def test_a_set_secret_variable_overrides_the_vault(store_env, monkeypatch):
    """`make up` mints fresh Splunk tokens into .env: they must win over older vault tokens."""
    conn, kek = store_env
    _configure(conn, kek)
    monkeypatch.setenv("SPLUNK_DEPLOY_TOKEN", "fresh-deploy")
    monkeypatch.setenv("SPLUNK_SEARCH_TOKEN", "fresh-search")
    monkeypatch.setenv("LLM_API_KEY", "")  # empty: not an override
    s = config.runtime()
    with s.secrets.use("splunk_deploy_token") as v:
        assert v == "fresh-deploy"  # not in the vault at all
    with s.secrets.use("splunk_search_token") as v:
        assert v == "fresh-search"  # in the vault too: the variable wins
    with s.secrets.use("llm_api_key") as v:
        assert v == KEY  # from the vault
    assert [s.secrets.source(n) for n in ("splunk_search_token", "llm_api_key")] == [
        "env override",
        "vault",
    ]
    assert "fresh-search" not in repr(s.secrets) and "env override" in repr(s.secrets)


def test_secret_variables_match_the_settings_fields():
    from parsemaxxing.settings import SettingsGroup

    declared = {
        cls.meta(f)["env"]
        for cls in SettingsGroup.registry.values()
        for f in cls.secret_fields()
        if cls.meta(f)["env"]
    }
    assert declared == set(config.LEGACY_SECRETS.values()) == set(config.V1_SECRETS)


def test_missing_required_settings_are_named(store_env):
    with pytest.raises(RuntimeError, match=r"llm.base_url \(LLM_BASE_URL\)"):
        config.runtime()


def test_local_runtime_needs_no_database(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("LLM_BASE_URL", "https://llm.example.com/v1")
    monkeypatch.setenv("LLM_MODEL", "m")
    monkeypatch.setenv("SPLUNK_HOST", "splunk.example.com")
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setenv("PARSEMAXXING_PACKAGES_DIR", str(tmp_path))
    s = config.runtime(local=True)
    assert s.dsn == "" and s.secrets.source("llm_api_key") == "env override"


# --- one-time v1 .env import ----------------------------------------------------------------


def _env_file(tmp_path, **extra):
    lines = {
        "LLM_BASE_URL": "https://llm.example.com/v1",
        "LLM_MODEL": "muse",
        "SPLUNK_HOST": "splunk.example.com",
        "SPLUNK_PORT": "8089",
        "PARSEMAXXING_TEST_INDEX": "pmx_lab",
        "LLM_API_KEY": KEY,
        "SPLUNK_SEARCH_TOKEN": TOKEN,
        "SPLUNK_DEPLOY_TOKEN": TOKEN + "-deploy",
        "POSTGRES_DB": "pmx",
    } | extra
    path = tmp_path / "v1.env"
    path.write_text("".join(f"{k}={v}\n" for k, v in lines.items()))
    return path


def _import(tmp_path, env_file, *flags):
    argv = ["--env-file", str(tmp_path / "none.env"), "settings", "import-env"]
    return cli_main([*argv, "--env-file", str(env_file), *flags])


def test_import_env_dry_run_then_apply_then_idempotent(store_env, tmp_path, capsys, caplog):
    conn, kek = store_env
    env_file = _env_file(tmp_path)

    assert _import(tmp_path, env_file, "--dry-run") == 0
    out = capsys.readouterr().out
    assert "dry run" in out and "llm.model [platform]: None -> 'muse'" in out
    assert "splunk.search_token [lab] (runtime source: vault): secret set (value not shown)" in out
    assert SettingsService(conn, {}).stored(LlmSettings, PLATFORM) == ({}, 0)  # nothing written

    assert _import(tmp_path, env_file) == 0
    out = capsys.readouterr().out
    svc = SettingsService(conn, {})
    assert svc.get(SplunkSettings, LAB).test_index == "pmx_lab"
    assert svc.get(LlmSettings, PLATFORM).model == "muse"
    ref = svc.get(SplunkSettings, LAB).search_token
    with Vault(conn, kek).use(ref, LAB) as p:
        assert p.text() == TOKEN
    assert "can be removed" in out and "SPLUNK_SEARCH_TOKEN" in out and "POSTGRES_DB" not in out

    history = len(svc.history(limit=1000))
    assert _import(tmp_path, env_file) == 0  # again: nothing changes
    out = capsys.readouterr().out
    assert "~" not in out and "secret unchanged" in out
    assert len(svc.history(limit=1000)) == history

    for text in (out, caplog.text, str(svc.history(limit=1000))):  # never a secret value
        assert TOKEN not in text and KEY not in text


def test_import_env_replaces_a_changed_secret_and_refuses_bad_values(store_env, tmp_path, capsys):
    conn, kek = store_env
    assert _import(tmp_path, _env_file(tmp_path)) == 0
    capsys.readouterr()
    assert _import(tmp_path, _env_file(tmp_path, SPLUNK_SEARCH_TOKEN="rotated-x")) == 0
    assert "search_token [lab] (runtime source: vault): secret replaced" in capsys.readouterr().out
    ref = SettingsService(conn, {}).get(SplunkSettings, LAB).search_token
    with Vault(conn, kek).use(ref, LAB) as p:
        assert p.text() == "rotated-x"
    assert _import(tmp_path, _env_file(tmp_path, PARSEMAXXING_TEST_INDEX="main")) == 4
    assert "PARSEMAXXING_TEST_INDEX is not a valid value" in capsys.readouterr().out
    assert SettingsService(conn, {}).get(SplunkSettings, LAB).test_index == "pmx_lab"


def test_import_env_refuses_a_base_url_with_credentials(store_env, tmp_path, capsys, caplog):
    conn, _ = store_env
    url = "https://user:synthetic-pw-5e7a@llm.example.com/v1"
    assert _import(tmp_path, _env_file(tmp_path, LLM_BASE_URL=url)) == 4
    out = capsys.readouterr()
    assert "LLM_BASE_URL is not a valid value" in out.out
    assert "synthetic-pw-5e7a" not in out.out + out.err + caplog.text
    assert SettingsService(conn, {}).stored(LlmSettings, PLATFORM)[0].get("base_url") is None


def test_import_env_needs_the_kek_unless_dry_run(store_env, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PARSEMAXXING_KEK_FILE", str(tmp_path / "missing"))
    env_file = _env_file(tmp_path)
    assert _import(tmp_path, env_file) == 4
    assert _import(tmp_path, env_file, "--dry-run") == 0


def test_import_env_shows_an_env_override_as_the_runtime_source(
    store_env, tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("SPLUNK_SEARCH_TOKEN", "fresh-search-1a2b")
    assert _import(tmp_path, _env_file(tmp_path)) == 0
    out = capsys.readouterr().out
    assert "splunk.search_token [lab] (runtime source: env override): secret set" in out
    assert "splunk.deploy_token [lab] (runtime source: vault)" in out
    assert "fresh-search-1a2b" not in out and TOKEN not in out


def test_imported_settings_drive_the_runtime(store_env, tmp_path):
    assert _import(tmp_path, _env_file(tmp_path)) == 0
    s = config.runtime()
    assert s.test_index == "pmx_lab" and s.secrets.source("splunk_deploy_token") == "vault"
    with s.secrets.use("splunk_deploy_token") as v:
        assert v == TOKEN + "-deploy"


def test_ledger_rows_are_written_only_by_the_store():
    offenders = [
        str(p.relative_to(PACKAGE))
        for p in PACKAGE.rglob("*.py")
        if p.name != "store.py" and "INSERT INTO ledger" in p.read_text(encoding="utf-8")
    ]
    assert offenders == []
