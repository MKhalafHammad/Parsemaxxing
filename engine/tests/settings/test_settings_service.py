"""Settings service: typed groups, scopes and inheritance, environment-variable overrides, history
(append-only for the app role), hash-addressed snapshots, export and import without secrets."""

import base64
import json
import os

import psycopg
import pytest

from parsemaxxing.ledger import store as db
from parsemaxxing.secrets import Kek, Vault
from parsemaxxing.settings import (
    PLATFORM,
    ConflictError,
    IngestSettings,
    LlmSettings,
    Scope,
    SettingsError,
    SettingsGroup,
    SettingsService,
    SplunkSettings,
    setting,
)

LAB, PROD, ACME = Scope("lab"), Scope("prod"), Scope("lab", "acme")
VALUE = "synthetic-token-value-4b1d"  # synthetic test value, not a real credential


@pytest.fixture
def conn(pg_dsn):
    c = db.connect(pg_dsn)
    with c.transaction():
        for t in ("settings_history", "settings_snapshots"):
            c.execute(f"ALTER TABLE {t} DISABLE TRIGGER {t}_no_truncate")
        c.execute(
            "TRUNCATE settings_groups, settings_history, settings_snapshots, secrets, vault_kek"
        )
        for t in ("settings_history", "settings_snapshots"):
            c.execute(f"ALTER TABLE {t} ENABLE TRIGGER {t}_no_truncate")
    yield c
    c.close()


@pytest.fixture
def svc(conn):
    return SettingsService(conn, environ={})


@pytest.fixture
def vault(conn, tmp_path):
    path = tmp_path / "kek"
    path.write_bytes(base64.b64encode(os.urandom(32)) + b"\n")
    path.chmod(0o400)
    return Vault(conn, Kek.load(path))


# --- models --------------------------------------------------------------------------------


def test_defaults_are_frozen_typed_models(svc):
    s = svc.get(SplunkSettings, LAB)
    assert (s.port, s.test_index, s.host) == (8089, "pmx_test", None)
    with pytest.raises(Exception):  # noqa: B017 - pydantic frozen instance error
        s.port = 1
    assert svc.get(IngestSettings, PLATFORM).daily_ingest_mb == 500


def test_bounds_and_unknown_fields_are_refused(svc):
    for values in ({"port": 0}, {"port": "x"}, {"nope": 1}):
        with pytest.raises(SettingsError):
            svc.set(SplunkSettings, LAB, values, actor="t")
    with pytest.raises(SettingsError):  # test indexes must start pmx_ (root rules)
        svc.set(SplunkSettings, LAB, {"test_index": "main"}, actor="t")
    assert svc.stored(SplunkSettings, LAB) == ({}, 0)


def test_group_definitions_are_checked():
    with pytest.raises(TypeError, match="bad env override"):

        class _Bad(SettingsGroup):
            GROUP = "bad_env_name"
            key: str | None = setting(None, env="lower-case")

    with pytest.raises(TypeError, match="defined twice"):

        class _Dup(SettingsGroup):
            GROUP = "llm"
            x: int = setting(1)


def test_scope_names_are_validated():
    for env, client in (("Lab", ""), ("", "acme"), ("a b", ""), ("../x", "")):
        with pytest.raises(SettingsError):
            Scope(env, client)


# --- scopes and inheritance ------------------------------------------------------------------


def test_inheritance_and_sources(svc):
    svc.set(SplunkSettings, PLATFORM, {"port": 8090}, actor="t")
    svc.set(SplunkSettings, LAB, {"host": "splunk-lab.example.com"}, actor="t")
    svc.set(SplunkSettings, ACME, {"test_index": "pmx_acme"}, actor="t")
    assert svc.get(SplunkSettings, ACME).port == 8090
    e = svc.explain(SplunkSettings, ACME)
    assert (e["port"].source, e["host"].source, e["test_index"].source) == (
        "platform",
        "environment",
        "client",
    )
    assert e["search_token"].source == "default" and e["search_token"].value is False
    assert svc.get(SplunkSettings, PROD).host is None  # nothing shared between environments
    assert svc.get(SplunkSettings, LAB).test_index == "pmx_test"
    svc.set(SplunkSettings, ACME, {}, actor="t", unset=("test_index",))  # reset to inherited
    assert svc.explain(SplunkSettings, ACME)["test_index"].source == "default"


def test_overrides_only_where_the_field_allows(svc, conn):
    with pytest.raises(SettingsError, match="cannot be set for a platform"):
        svc.set(SplunkSettings, PLATFORM, {"host": "splunk.example.com"}, actor="t")
    with pytest.raises(SettingsError, match="cannot be set for a client"):
        svc.set(SplunkSettings, ACME, {"port": 9000}, actor="t")
    with pytest.raises(SettingsError, match="cannot be set for a environment"):
        svc.set(LlmSettings, LAB, {"model": "m"}, actor="t")
    # a row written around the service at a disallowed level is ignored, not obeyed
    conn.execute(
        "INSERT INTO settings_groups (environment, client, grp, version, schema_version, value,"
        " updated_by) VALUES ('lab', 'acme', 'splunk', 1, 1, '{\"port\": 9000}', 't')"
    )
    assert svc.get(SplunkSettings, ACME).port == 8089


def test_newer_schema_version_and_invalid_stored_rows_fail_closed(svc, conn):
    conn.execute(
        "INSERT INTO settings_groups (environment, client, grp, version, schema_version, value,"
        " updated_by) VALUES ('', '', 'ingest', 1, 99, '{}', 't'),"
        " ('lab', '', 'splunk', 1, 1, '{\"port\": -1}', 't')"
    )
    with pytest.raises(SettingsError, match="version 99"):
        svc.get(IngestSettings, PLATFORM)
    with pytest.raises(SettingsError, match=r"\['port'\]"):
        svc.get(SplunkSettings, LAB)


def test_optimistic_version(svc):
    v1 = svc.set(IngestSettings, PLATFORM, {"job_ingest_mb": 10}, actor="t")
    assert v1 == 1
    assert svc.set(IngestSettings, PLATFORM, {"job_ingest_mb": 11}, "t", expected_version=1) == 2
    with pytest.raises(ConflictError):
        svc.set(IngestSettings, PLATFORM, {"job_ingest_mb": 12}, "t", expected_version=1)
    assert svc.set(IngestSettings, PLATFORM, {"job_ingest_mb": 11}, actor="t") == 2  # no-op


# --- environment-variable overrides -------------------------------------------------------------


def test_environment_variables_override_and_are_read_only(conn):
    svc = SettingsService(conn, environ={"SPLUNK_PORT": "8091", "LLM_MODEL": "env-model"})
    assert svc.get(SplunkSettings, LAB).port == 8091
    e = svc.explain(SplunkSettings, LAB)["port"]
    assert (e.source, e.read_only) == ("environment variable", True)
    for group, scope, values in (
        (SplunkSettings, LAB, {"port": 1}),
        (LlmSettings, PLATFORM, {"model": "x"}),
    ):
        with pytest.raises(SettingsError, match="managed by environment variable"):
            svc.set(group, scope, values, actor="t")
    with pytest.raises(SettingsError, match="SPLUNK_PORT"):
        SettingsService(conn, environ={"SPLUNK_PORT": "nan"}).get(SplunkSettings, LAB)


@pytest.mark.parametrize(
    "url",
    [
        "https://user:synthetic-pw-91c2@llm.example.com/v1",
        "https://synthetic-user-only-91c2@llm.example.com/v1",
        "https://:synthetic-pw-91c2@llm.example.com/v1",
    ],
)
def test_url_settings_refuse_credentials_without_echoing_them(svc, conn, url):
    """Adversarial: a credential in a URL setting would be stored and shown in clear."""
    with pytest.raises(SettingsError) as e:
        svc.set(LlmSettings, PLATFORM, {"base_url": url}, actor="t")
    assert "base_url" in str(e.value) and "synthetic" not in str(e.value)
    with pytest.raises(SettingsError) as e:
        SettingsService(conn, environ={"LLM_BASE_URL": url}).get(LlmSettings, PLATFORM)
    assert "LLM_BASE_URL" in str(e.value) and "synthetic" not in str(e.value)
    assert svc.stored(LlmSettings, PLATFORM)[0].get("base_url") is None
    svc.set(LlmSettings, PLATFORM, {"base_url": "https://llm.example.com/v1"}, actor="t")


ENV_TOKEN = "synthetic-env-tok-0c4e"  # noqa: S105  # gitleaks:allow - synthetic


def test_a_secret_variable_is_a_read_only_override_whose_value_is_never_read(svc, conn, vault):
    ref = vault.put(LAB, "splunk.search_token", VALUE, "t")
    svc.set(SplunkSettings, LAB, {"search_token": ref}, actor="t")
    env = SettingsService(conn, environ={"SPLUNK_SEARCH_TOKEN": ENV_TOKEN})
    e = env.explain(SplunkSettings, LAB)["search_token"]
    assert (e.value, e.source, e.read_only, e.secret) == (True, "environment variable", True, True)
    assert env.get(SplunkSettings, LAB).search_token == ref  # the value never enters settings
    assert ENV_TOKEN not in repr(env.explain(SplunkSettings, LAB))
    with pytest.raises(SettingsError, match="managed by environment variable SPLUNK_SEARCH_TOKEN"):
        env.set(SplunkSettings, LAB, {"search_token": None}, actor="t")
    # Unset and empty variables are not overrides: the vault id applies.
    for environ in ({}, {"SPLUNK_SEARCH_TOKEN": ""}):
        e = SettingsService(conn, environ).explain(SplunkSettings, LAB)["search_token"]
        assert (e.value, e.source, e.read_only) == (True, "environment", False)
    e = SettingsService(conn, {"LLM_API_KEY": "x"}).explain(LlmSettings, PLATFORM)["api_key"]
    assert (e.value, e.source) == (True, "environment variable")  # set by the variable alone


# --- secrets in settings --------------------------------------------------------------------------


def test_secret_fields_take_only_a_vault_id_of_the_same_scope(svc, vault):
    lab_token = vault.put(LAB, "splunk.search", VALUE, actor="t")
    prod_token = vault.put(PROD, "splunk.search", VALUE, actor="t")
    with pytest.raises(SettingsError):  # a value instead of a reference
        svc.set(SplunkSettings, LAB, {"search_token": VALUE}, actor="t")
    with pytest.raises(SettingsError, match="no such secret in this scope"):
        svc.set(SplunkSettings, LAB, {"search_token": prod_token}, actor="t")
    svc.set(SplunkSettings, LAB, {"search_token": lab_token}, actor="t")
    s = svc.get(SplunkSettings, LAB)
    with vault.use(s.search_token, LAB) as p:
        assert p.text() == VALUE
    assert svc.explain(SplunkSettings, LAB)["search_token"].value is True
    (h,) = svc.history(LAB, "splunk")
    assert h["redacted"] and h["old_value"] is None and h["new_value"] is None


# --- history ------------------------------------------------------------------------------------


def test_history_records_every_change_per_scope(svc):
    svc.set(SplunkSettings, LAB, {"host": "a.example.com", "port": 8090}, actor="alice")
    svc.set(SplunkSettings, LAB, {"port": 8091}, actor="bob", unset=("host",))
    svc.set(SplunkSettings, PROD, {"port": 9000}, actor="bob")
    rows = svc.history(LAB)
    assert [
        (r["field"], r["action"], r["old_value"], r["new_value"], r["actor"]) for r in rows
    ] == [
        ("port", "set", 8090, 8091, "bob"),
        ("host", "reset", "a.example.com", None, "bob"),
        ("port", "set", None, 8090, "alice"),
        ("host", "set", None, "a.example.com", "alice"),
    ]
    assert len(svc.history()) == 5 and len(svc.history(PROD, "splunk")) == 1
    assert svc.history(PROD, "llm") == []


def test_history_is_append_only_for_the_app_role(svc, pg_dsn):
    svc.set(IngestSettings, PLATFORM, {"job_ingest_mb": 10}, actor="t")
    app = db.connect(pg_dsn)
    app.execute("SET ROLE parsemaxxing_app")
    SettingsService(app, {}).set(IngestSettings, PLATFORM, {"job_ingest_mb": 11}, actor="app")
    for sql in (
        "UPDATE settings_history SET actor = 'x'",
        "DELETE FROM settings_history",
        "TRUNCATE settings_history",
        "ALTER TABLE settings_history DISABLE TRIGGER settings_history_no_update",
        "DROP TRIGGER settings_history_no_update ON settings_history",
        "UPDATE settings_snapshots SET body = '{}'",
        "DELETE FROM settings_groups",
        "UPDATE settings_groups SET environment = 'prod'",
    ):
        with pytest.raises((psycopg.errors.InsufficientPrivilege, psycopg.errors.RaiseException)):
            app.execute(sql)
    app.close()
    assert len(svc.history()) == 2


def test_history_is_append_only_even_for_the_owner(svc, conn):
    svc.set(IngestSettings, PLATFORM, {"job_ingest_mb": 10}, actor="t")
    for sql in ("UPDATE settings_history SET actor = 'x'", "DELETE FROM settings_history"):
        with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
            conn.execute(sql)


# --- snapshots ---------------------------------------------------------------------------------


def test_snapshot_is_hash_addressed_and_frozen_in_time(svc, conn):
    svc.set(SplunkSettings, LAB, {"host": "a.example.com"}, actor="t")
    h1 = svc.snapshot(LAB)
    assert len(h1) == 64 and svc.snapshot(LAB) == h1  # same settings, same hash, one row
    svc.set(SplunkSettings, LAB, {"host": "b.example.com"}, actor="t")
    h2 = svc.snapshot(LAB)
    assert h2 != h1
    assert svc.load_snapshot(h1)["splunk"].host == "a.example.com"  # a running job's view
    assert svc.load_snapshot(h2)["splunk"].host == "b.example.com"
    assert conn.execute("SELECT count(*) AS n FROM settings_snapshots").fetchone()["n"] == 2
    # an altered snapshot body is detected (owner bypassing the trigger)
    with conn.transaction():
        conn.execute("ALTER TABLE settings_snapshots DISABLE TRIGGER settings_snapshots_no_update")
        conn.execute(
            "UPDATE settings_snapshots SET body = jsonb_set(body, '{scope,client}',"
            " '\"x\"') WHERE hash = %s",
            (h1,),
        )
        conn.execute("ALTER TABLE settings_snapshots ENABLE TRIGGER settings_snapshots_no_update")
    with pytest.raises(SettingsError, match="missing or altered"):
        svc.load_snapshot(h1)
    with pytest.raises(SettingsError):
        svc.load_snapshot("0" * 64)


# --- export and import --------------------------------------------------------------------------


def test_export_never_contains_secrets_and_import_round_trips(svc, vault):
    token = vault.put(LAB, "splunk.search", VALUE, actor="t")
    svc.set(SplunkSettings, LAB, {"host": "a.example.com", "search_token": token}, actor="t")
    svc.set(IngestSettings, LAB, {}, actor="t")  # no row
    doc = svc.export(LAB)
    blob = json.dumps(doc)
    assert VALUE not in blob and token not in blob and "search_token" not in blob
    assert doc["groups"] == {"splunk": {"version": 1, "values": {"host": "a.example.com"}}}
    # clone into another environment: a diff first, then apply; secrets are never copied
    plan = svc.plan_import(doc, PROD)
    assert [(c.group, c.field, c.old, c.new) for c in plan] == [
        ("splunk", "host", None, "a.example.com")
    ]
    assert svc.stored(SplunkSettings, PROD) == ({}, 0)  # planning writes nothing
    assert svc.apply_import(doc, PROD, actor="t") == plan
    assert svc.export(PROD)["groups"] == doc["groups"]
    assert svc.get(SplunkSettings, PROD).search_token is None
    assert svc.plan_import(doc, PROD) == []
    # importing over an existing scope replaces non-secret values and keeps the secret
    svc.set(SplunkSettings, LAB, {"port": 9000}, actor="t")
    svc.apply_import(doc, LAB, actor="t")
    s = svc.get(SplunkSettings, LAB)
    assert (s.port, s.search_token) == (8089, token)


@pytest.mark.parametrize(
    "doc",
    [
        {"format": "other", "scope": {}, "groups": {}},
        {"format": "parsemaxxing-settings/1", "scope": {}, "groups": {}, "extra": 1},
        {
            "format": "parsemaxxing-settings/1",
            "scope": {},
            "groups": {"nope": {"version": 1, "values": {}}},
        },
        {
            "format": "parsemaxxing-settings/1",
            "scope": {},
            "groups": {"splunk": {"version": 2, "values": {}}},
        },
        {
            "format": "parsemaxxing-settings/1",
            "scope": {},
            "groups": {"splunk": {"version": 1, "values": {"search_token": VALUE}}},
        },
        {
            "format": "parsemaxxing-settings/1",
            "scope": {},
            "groups": {"splunk": {"version": 1, "values": {"port": 70000}}},
        },
        "not json object",
    ],
)
def test_invalid_imports_are_refused_and_change_nothing(svc, doc):
    with pytest.raises(SettingsError) as e:
        svc.apply_import(doc, LAB, actor="t")
    assert VALUE not in str(e.value)
    assert svc.history() == []


def test_import_is_atomic(svc):
    doc = {
        "format": "parsemaxxing-settings/1",
        "scope": {},
        "groups": {
            "ingest": {"version": 1, "values": {"job_ingest_mb": 5}},
            "splunk": {"version": 1, "values": {"port": 70000}},
        },
    }
    with pytest.raises(SettingsError):
        svc.apply_import(doc, PLATFORM, actor="t")
    assert svc.stored(IngestSettings, PLATFORM) == ({}, 0)


def test_import_refuses_to_change_env_managed_fields(conn):
    svc = SettingsService(conn, environ={"SPLUNK_PORT": "8091"})
    doc = {
        "format": "parsemaxxing-settings/1",
        "scope": {},
        "groups": {"splunk": {"version": 1, "values": {"port": 1}}},
    }
    with pytest.raises(SettingsError, match="managed by environment"):
        svc.plan_import(doc, LAB)
    doc["groups"]["splunk"]["values"] = {"host": "a.example.com"}
    assert len(svc.plan_import(doc, LAB)) == 1  # untouched env-managed fields are fine
