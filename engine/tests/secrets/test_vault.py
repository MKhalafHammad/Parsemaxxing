"""Vault: envelope encryption, AAD binding, KEK file rules, scope isolation, rotation, redaction.
Includes the adversarial cases (tampered and moved ciphertext, wrong KEK, readable KEK file)."""

import base64
import logging
import os
import pickle
import threading
import time

import psycopg
import pytest

from parsemaxxing.cli import main as cli_main
from parsemaxxing.ledger import store as db
from parsemaxxing.secrets import Kek, Vault, VaultError, kek_file, rotate_kek
from parsemaxxing.secrets.vault import _check_kek
from parsemaxxing.settings import PLATFORM, Scope

VALUE = "synthetic-secret-value-7f3a9c"  # synthetic test value, not a real credential
LAB = Scope("lab")


def write_kek(path, mode=0o400, key: bytes | None = None):
    path.write_bytes(base64.b64encode(key or os.urandom(32)) + b"\n")
    path.chmod(mode)
    return path


@pytest.fixture
def conn(pg_dsn):
    c = db.connect(pg_dsn)
    with c.transaction():
        c.execute("ALTER TABLE settings_history DISABLE TRIGGER settings_history_no_truncate")
        c.execute("TRUNCATE secrets, vault_kek, settings_history")
        c.execute("ALTER TABLE settings_history ENABLE TRIGGER settings_history_no_truncate")
    yield c
    c.close()


@pytest.fixture
def kek(tmp_path):
    return Kek.load(write_kek(tmp_path / "kek"))


# --- KEK file ------------------------------------------------------------------------------


def test_kek_file_path_comes_from_bootstrap_env_with_docker_secret_default(tmp_path):
    assert str(kek_file({})) == "/run/secrets/pmx_kek"
    assert kek_file({"PARSEMAXXING_KEK_FILE": str(tmp_path / "k")}) == tmp_path / "k"


@pytest.mark.parametrize("mode", [0o644, 0o440, 0o404, 0o600 | 0o020])
def test_kek_file_readable_by_group_or_others_is_refused(tmp_path, mode):
    path = write_kek(tmp_path / "kek", mode=mode)
    with pytest.raises(VaultError, match="readable by group or others"):
        Kek.load(path)


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"not base64!!\n",
        base64.b64encode(os.urandom(16)) + b"\n",
        base64.b64encode(os.urandom(32)) + b"\n\n",
        b" " + base64.b64encode(os.urandom(32)),
    ],
)
def test_kek_file_must_be_one_line_of_base64_of_32_bytes(tmp_path, content):
    path = tmp_path / "kek"
    path.write_bytes(content)
    path.chmod(0o400)
    with pytest.raises(VaultError):
        Kek.load(path)


def test_kek_file_symlink_and_missing_file_are_refused(tmp_path):
    real = write_kek(tmp_path / "real")
    (tmp_path / "link").symlink_to(real)
    with pytest.raises(VaultError):
        Kek.load(tmp_path / "link")
    with pytest.raises(VaultError, match="cannot open"):
        Kek.load(tmp_path / "missing")


def test_kek_repr_and_pickle_never_expose_the_key(tmp_path):
    key = os.urandom(32)
    k = Kek.load(write_kek(tmp_path / "kek", key=key))
    for text in (repr(k), str(k), f"{k}"):
        assert key.hex() not in text and base64.b64encode(key).decode() not in text
    with pytest.raises(TypeError):
        pickle.dumps(k)


# --- round trip, redaction ------------------------------------------------------------------


def test_round_trip_and_plaintext_only_inside_the_block(conn, kek):
    vault = Vault(conn, kek)
    sid = vault.put(LAB, "splunk.search_token", VALUE, actor="t")
    with vault.use(sid, LAB) as p:
        assert p.text() == VALUE
        assert VALUE not in repr(p) and VALUE not in str(p) and VALUE not in f"{p}"
        with pytest.raises(TypeError):
            pickle.dumps(p)
        kept = p
    with pytest.raises(VaultError, match="only usable inside"):
        kept.reveal()
    row = conn.execute("SELECT * FROM secrets WHERE id = %s", (sid,)).fetchone()
    assert VALUE.encode() not in bytes(row["ciphertext"]) and len(row["nonce"]) == 12


def test_replacing_a_secret_keeps_the_id_and_uses_a_new_key_and_nonce(conn, kek):
    vault = Vault(conn, kek)
    sid = vault.put(LAB, "tok", VALUE, actor="t")
    before = conn.execute("SELECT * FROM secrets WHERE id = %s", (sid,)).fetchone()
    assert vault.put(LAB, "tok", VALUE + "-2", actor="t") == sid
    after = conn.execute("SELECT * FROM secrets WHERE id = %s", (sid,)).fetchone()
    assert after["version"] == 2
    assert bytes(after["nonce"]) != bytes(before["nonce"])
    assert bytes(after["wrapped_dek"]) != bytes(before["wrapped_dek"])
    with vault.use(sid, LAB) as p:
        assert p.text() == VALUE + "-2"
    assert vault.info(sid, LAB).version == 2


def test_bad_names_and_empty_values_are_refused(conn, kek):
    vault = Vault(conn, kek)
    for name in ("", "Upper", "a b", "x" * 200, "a\nb"):
        with pytest.raises(VaultError):
            vault.put(LAB, name, VALUE, actor="t")
    with pytest.raises(VaultError, match="empty"):
        vault.put(LAB, "tok", "", actor="t")


# --- adversarial: tampering, moving, wrong KEK -------------------------------------------------


def _owner_update(conn, sql, params):
    conn.execute(sql, params)  # the test DSN is the owner; an attacker with DB write access


@pytest.mark.parametrize("column", ["ciphertext", "nonce", "wrapped_dek", "dek_nonce"])
def test_tampered_row_fails_closed(conn, kek, column):
    vault = Vault(conn, kek)
    sid = vault.put(LAB, "tok", VALUE, actor="t")
    raw = bytearray(
        conn.execute(f"SELECT {column} FROM secrets WHERE id = %s", (sid,)).fetchone()[column]  # noqa: S608
    )
    raw[0] ^= 1
    _owner_update(conn, f"UPDATE secrets SET {column} = %s WHERE id = %s", (bytes(raw), sid))  # noqa: S608
    with pytest.raises(VaultError, match="failed authentication") as e, vault.use(sid, LAB):
        pass
    assert VALUE not in str(e.value) and e.value.__cause__ is None


@pytest.mark.parametrize("column", ["version", "name", "environment"])
def test_changed_aad_fields_fail_closed(conn, kek, column):
    vault = Vault(conn, kek)
    sid = vault.put(LAB, "tok", VALUE, actor="t")
    value = {"version": 2, "name": "other", "environment": "prod"}[column]
    _owner_update(conn, f"UPDATE secrets SET {column} = %s WHERE id = %s", (value, sid))  # noqa: S608
    scope = Scope("prod") if column == "environment" else LAB
    with pytest.raises(VaultError, match="failed authentication"), vault.use(sid, scope):
        pass


def test_ciphertext_moved_to_another_row_fails_closed(conn, kek):
    vault = Vault(conn, kek)
    a = vault.put(LAB, "a", VALUE, actor="t")
    b = vault.put(LAB, "b", "other-synthetic-value", actor="t")
    src = conn.execute("SELECT * FROM secrets WHERE id = %s", (a,)).fetchone()
    # Move only the value (b's own wrapped key), then the whole envelope.
    _owner_update(
        conn,
        "UPDATE secrets SET nonce = %s, ciphertext = %s WHERE id = %s",
        (src["nonce"], src["ciphertext"], b),
    )
    with pytest.raises(VaultError, match="failed authentication"), vault.use(b, LAB):
        pass
    _owner_update(
        conn,
        "UPDATE secrets SET dek_nonce = %s, wrapped_dek = %s WHERE id = %s",
        (src["dek_nonce"], src["wrapped_dek"], b),
    )
    with pytest.raises(VaultError, match="failed authentication"), vault.use(b, LAB):
        pass


def test_wrong_kek_fails_closed_even_if_the_kek_id_check_is_bypassed(conn, kek, tmp_path):
    sid = Vault(conn, kek).put(LAB, "tok", VALUE, actor="t")
    wrong = Kek.load(write_kek(tmp_path / "wrong"))
    with pytest.raises(VaultError, match="not the vault's KEK"), Vault(conn, wrong).use(sid, LAB):
        pass
    with pytest.raises(VaultError, match="not the vault's KEK"):
        Vault(conn, wrong).put(LAB, "tok2", VALUE, actor="t")
    _owner_update(conn, "UPDATE vault_kek SET kek_id = %s", (wrong.id,))
    with pytest.raises(VaultError, match="failed authentication"), Vault(conn, wrong).use(sid, LAB):
        pass


def test_a_secret_resolves_only_in_its_own_scope(conn, kek):
    vault = Vault(conn, kek)
    sid = vault.put(LAB, "tok", VALUE, actor="t")
    for scope in (PLATFORM, Scope("prod"), Scope("lab", "acme")):
        with pytest.raises(VaultError, match="no such secret in this scope"), vault.use(sid, scope):
            pass
        with pytest.raises(VaultError):
            vault.info(sid, scope)
    assert [s.name for s in vault.list(LAB)] == ["tok"] and vault.list(PLATFORM) == []
    with pytest.raises(VaultError), vault.use("not-a-uuid", LAB):
        pass


def test_app_role_cannot_move_a_secret_to_another_scope_or_delete_it(conn, kek, pg_dsn):
    sid = Vault(conn, kek).put(LAB, "tok", VALUE, actor="t")
    app = db.connect(pg_dsn)
    app.execute("SET ROLE parsemaxxing_app")
    for sql in (
        "UPDATE secrets SET environment = 'prod'",
        "UPDATE secrets SET name = 'x'",
        "UPDATE secrets SET id = gen_random_uuid()",
        "DELETE FROM secrets",
        "TRUNCATE secrets",
    ):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            app.execute(sql)
    with Vault(app, kek).use(sid, LAB) as p:  # what the engine needs works
        assert p.text() == VALUE
    app.close()


# --- rotation ------------------------------------------------------------------------------


def test_rotate_kek_round_trip(conn, kek, tmp_path):
    vault = Vault(conn, kek)
    ids = [vault.put(LAB, f"s{i}", f"{VALUE}-{i}", actor="t") for i in range(3)]
    ids.append(vault.put(Scope("lab", "acme"), "c", VALUE, actor="t"))
    new = Kek.load(write_kek(tmp_path / "new"))
    before = conn.execute("SELECT id, ciphertext, nonce FROM secrets ORDER BY id").fetchall()
    assert rotate_kek(conn, kek, new, actor="t") == 4
    after = conn.execute("SELECT id, ciphertext, nonce FROM secrets ORDER BY id").fetchall()
    assert before == after  # values untouched, only the data keys rewrapped
    for i, sid in enumerate(ids[:3]):
        with Vault(conn, new).use(sid, LAB) as p:
            assert p.text() == f"{VALUE}-{i}"
    with pytest.raises(VaultError, match="not the vault's KEK"), vault.use(ids[0], LAB):
        pass
    assert (
        conn.execute(
            "SELECT count(*) AS n FROM settings_history WHERE action = 'kek_rotated'"
        ).fetchone()["n"]
        == 1
    )


def test_rotate_kek_is_all_or_nothing(conn, kek, tmp_path):
    vault = Vault(conn, kek)
    a = vault.put(LAB, "a", VALUE, actor="t")
    b = vault.put(LAB, "b", VALUE, actor="t")
    _owner_update(conn, "UPDATE secrets SET version = 9 WHERE id = %s", (max(a, b),))
    new = Kek.load(write_kek(tmp_path / "new"))
    with pytest.raises(VaultError):
        rotate_kek(conn, kek, new, actor="t")
    with vault.use(min(a, b), LAB) as p:  # still the old KEK: nothing was rewrapped
        assert p.text() == VALUE
    with pytest.raises(VaultError, match="current KEK"):
        rotate_kek(conn, kek, kek, actor="t")
    with pytest.raises(VaultError, match="not the vault's KEK"):
        rotate_kek(conn, new, kek, actor="t")


def test_cli_rotate_kek(conn, kek, tmp_path, monkeypatch, capsys, pg_dsn):
    old_file = write_kek(tmp_path / "old")
    old = Kek.load(old_file)
    sid = Vault(conn, old).put(LAB, "tok", VALUE, actor="t")
    new_file = write_kek(tmp_path / "new")
    monkeypatch.setenv("PARSEMAXXING_KEK_FILE", str(old_file))
    monkeypatch.setenv("DATABASE_URL", pg_dsn)
    env_file = tmp_path / "none.env"
    assert (
        cli_main(
            ["--env-file", str(env_file), "secrets", "rotate-kek", "--new-kek-file", str(new_file)]
        )
        == 0
    )
    with Vault(conn, Kek.load(new_file)).use(sid, LAB) as p:
        assert p.text() == VALUE
    new_file.chmod(0o644)
    assert (
        cli_main(
            ["--env-file", str(env_file), "secrets", "rotate-kek", "--new-kek-file", str(new_file)]
        )
        == 4
    )
    out = capsys.readouterr()
    assert "readable by group or others" in out.err and VALUE not in out.out + out.err


def test_rotate_kek_as_the_app_role(conn, kek, tmp_path, pg_dsn):
    """The deployed CLI connects as parsemaxxing_app (column-level UPDATE, no table lock)."""
    vault = Vault(conn, kek)
    sid = vault.put(LAB, "tok", VALUE, actor="t")
    new = Kek.load(write_kek(tmp_path / "new"))
    app = db.connect(pg_dsn)
    app.execute("SET ROLE parsemaxxing_app")
    try:
        assert rotate_kek(app, kek, new, actor="t") == 1
        with Vault(app, new).use(sid, LAB) as p:
            assert p.text() == VALUE
    finally:
        app.close()


def test_rotation_waits_for_a_running_put_and_refuses_its_old_kek_after(
    conn, kek, tmp_path, pg_dsn
):
    """vault_kek FOR UPDATE (rotate) against FOR SHARE (put): no DEK is wrapped with the old KEK
    after the rotation commits."""
    sid = Vault(conn, kek).put(LAB, "tok", VALUE, actor="t")
    new = Kek.load(write_kek(tmp_path / "new"))
    rot = db.connect(pg_dsn)
    done = []
    try:
        with conn.transaction():
            _check_kek(conn, kek, "FOR SHARE")  # a put in progress
            t = threading.Thread(target=lambda: done.append(rotate_kek(rot, kek, new, "t")))
            t.start()
            _wait_for_lock_wait(conn)
            assert done == []  # rotation waits for the put
        t.join(10)
        assert done == [1]
        with pytest.raises(VaultError, match="not the vault's KEK"):
            Vault(conn, kek).put(LAB, "tok", VALUE, actor="t")
        with Vault(conn, new).use(sid, LAB) as p:
            assert p.text() == VALUE
    finally:
        rot.close()


def test_cli_rotate_kek_reports_a_missing_grant_without_sql(
    conn, tmp_path, monkeypatch, capsys, pg_dsn
):
    import parsemaxxing.secrets as secrets

    def denied(*a, **k):
        raise psycopg.errors.InsufficientPrivilege(
            "permission denied for table secrets DETAIL: synthetic-sql-detail"
        )

    monkeypatch.setattr(secrets, "rotate_kek", denied)
    monkeypatch.setenv("DATABASE_URL", pg_dsn)
    monkeypatch.setenv("PARSEMAXXING_KEK_FILE", str(write_kek(tmp_path / "old")))
    argv = ["--env-file", str(tmp_path / "none.env"), "secrets", "rotate-kek", "--new-kek-file"]
    assert cli_main([*argv, str(write_kek(tmp_path / "new"))]) == 4
    out = capsys.readouterr()
    assert "lacks a privilege" in out.err and "nothing was changed" in out.err
    assert "synthetic-sql-detail" not in out.out + out.err and "Traceback" not in out.err


# --- first use of a KEK (adversarial) --------------------------------------------------------


def _wait_for_lock_wait(conn):
    for _ in range(100):
        if conn.execute("SELECT 1 FROM pg_locks WHERE NOT granted").fetchone():
            return
        time.sleep(0.05)
    raise AssertionError("the other session never waited")


def test_a_kek_is_not_adopted_by_a_vault_that_has_secrets(conn, kek, tmp_path):
    sid = Vault(conn, kek).put(LAB, "tok", VALUE, actor="t")
    conn.execute("DELETE FROM vault_kek")  # owner: the KEK id row is lost
    other = Kek.load(write_kek(tmp_path / "other"))
    new = Kek.load(write_kek(tmp_path / "new"))
    for k in (other, kek):  # even the right KEK: the id is gone, nothing proves it
        with pytest.raises(VaultError, match="no KEK id"):
            Vault(conn, k).put(LAB, "tok2", VALUE, actor="t")
        with pytest.raises(VaultError, match="no KEK id"), Vault(conn, k).use(sid, LAB):
            pass
        with pytest.raises(VaultError, match="no KEK id"):
            rotate_kek(conn, k, new, actor="t")
    assert conn.execute("SELECT count(*) AS n FROM vault_kek").fetchone()["n"] == 0


@pytest.mark.parametrize("same", [True, False])
def test_concurrent_first_use_keeps_one_kek(conn, kek, tmp_path, pg_dsn, same):
    second = kek if same else Kek.load(write_kek(tmp_path / "other"))
    other = db.connect(pg_dsn)
    result = []

    def first_use():
        try:
            Vault(other, second).put(LAB, "b", VALUE, actor="t")
            result.append("ok")
        except VaultError as e:
            result.append(str(e))

    try:
        with conn.transaction():
            _check_kek(conn, kek, "FOR SHARE")  # records kek, not committed yet
            t = threading.Thread(target=first_use)
            t.start()
            _wait_for_lock_wait(conn)
        t.join(10)
    finally:
        other.close()
    assert result == (
        ["ok"] if same else ["this KEK is not the vault's KEK (wrong file, or rotated elsewhere)"]
    )
    (row,) = conn.execute("SELECT kek_id FROM vault_kek").fetchall()
    assert row["kek_id"] == kek.id


# --- leakage scan ----------------------------------------------------------------------------


def test_secret_value_never_in_logs_errors_or_history(conn, kek, tmp_path, caplog, capsys):
    caplog.set_level(logging.DEBUG)
    vault = Vault(conn, kek)
    sid = vault.put(LAB, "tok", VALUE, actor="t")
    vault.put(LAB, "tok", VALUE + "-2", actor="t")
    errors = []
    for scope in (LAB, PLATFORM):
        try:
            with vault.use(sid, scope) as p:
                raise RuntimeError(f"boom {p!r} {p}")
        except (VaultError, RuntimeError) as e:
            errors.append(f"{e!r} {e}")
    _owner_update(conn, "UPDATE secrets SET version = 7 WHERE id = %s", (sid,))
    try:
        with vault.use(sid, LAB):
            pass
    except VaultError as e:
        errors.append(f"{e!r} {e}")
    history = conn.execute("SELECT * FROM settings_history").fetchall()
    assert [h["action"] for h in history] == ["secret_changed", "secret_changed"]
    assert all(h["redacted"] and h["old_value"] is None for h in history)
    out = capsys.readouterr()
    blob = " ".join(
        [
            *errors,
            caplog.text,
            out.out,
            out.err,
            repr(history),
            repr(vault),
            repr(vault.info(sid, LAB)),
        ]
    )
    assert VALUE not in blob and len(errors) == 3
