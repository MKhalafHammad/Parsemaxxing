"""Encrypted backups: argument lists (no password or key on a command line), file modes,
pruning, the CLI's refusals, and one real pg_dump | age round trip when the tools exist."""

import os
import shutil
import subprocess
import time
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest

from parsemaxxing.cli import main as cli_main
from parsemaxxing.ledger import backup
from parsemaxxing.ledger import store as db

RECIPIENT = "age1" + "q" * 58  # well-formed, not a real key
DSN = "postgresql://owner:pa%40ss@db.example.com:5432/pmx"
HEAD = "7:" + "a" * 64


def test_password_leaves_the_connection_string_for_the_environment():
    conninfo, env = backup.split_dsn(DSN)
    assert env == {"PGPASSWORD": "pa@ss"}
    assert "pa@ss" not in conninfo and "pa%40ss" not in conninfo and "dbname=pmx" in conninfo
    for argv in (backup.dump_argv(conninfo), backup.restore_argv(conninfo)):
        assert not any("pa@ss" in a for a in argv)
    assert backup.split_dsn("postgresql://u@h/d")[1] == {}


def test_argument_lists():
    assert backup.dump_argv("dbname=x")[:3] == ["pg_dump", "--format=custom", "--no-owner"]
    restore = backup.restore_argv("dbname=x")
    assert "--single-transaction" in restore and "--exit-on-error" in restore
    assert backup.encrypt_argv(RECIPIENT) == ["age", "--encrypt", "--recipient", RECIPIENT]
    assert backup.decrypt_argv(backup.Path("/k")) == ["age", "--decrypt", "--identity", "/k"]


@pytest.mark.parametrize(
    "bad", ["", "age1short", "AGE1" + "q" * 58, "age1" + "b" * 58, RECIPIENT + " -o /etc/x"]
)
def test_bad_recipient_is_refused_before_anything_runs(bad, tmp_path):
    with pytest.raises(backup.BackupError):
        backup.backup(DSN, bad, tmp_path / "b", {}, HEAD)
    assert not (tmp_path / "b").exists()


def test_failed_pipe_leaves_no_partial_file(tmp_path, monkeypatch):
    def fail(*a, **k):
        raise backup.BackupError("pg_dump | age failed")

    monkeypatch.setattr(backup, "_pipe", fail)
    with pytest.raises(backup.BackupError):
        backup.backup(DSN, RECIPIENT, tmp_path / "b", {}, HEAD)
    assert list((tmp_path / "b").iterdir()) == []
    assert (tmp_path / "b").stat().st_mode & 0o777 == 0o700


def test_backup_file_modes_and_pruning(tmp_path, monkeypatch):
    seen = {}

    def fake_pipe(first, second, envs, stdin, stdout):
        seen.update(first=first, second=second, envs=envs)
        stdout.write(backup.AGE_HEADER + b"...")

    monkeypatch.setattr(backup, "_pipe", fake_pipe)
    out = tmp_path / "b"
    out.mkdir(mode=0o755)
    old = out / "pmx-20200101T000000Z.dump.age"
    old.write_bytes(b"old")
    os.utime(old, (time.time() - 31 * 86400,) * 2)
    keep = out / "notes.txt"  # not ours: never pruned
    keep.write_text("x")
    os.utime(keep, (time.time() - 90 * 86400,) * 2)
    old_side = backup.sidecar(old)
    old_side.write_text("x")
    environ = {
        "PATH": "/usr/bin",
        "HOME": "/h",
        "LANG": "C",
        "PGSSLMODE": "require",
        "LLM_API_KEY": "synthetic-not-for-children",  # synthetic test value
        "DATABASE_URL": "postgresql://u:p@h/d",
    }
    path = backup.backup(DSN, RECIPIENT, out, environ, HEAD)
    assert path.read_bytes() == backup.AGE_HEADER + b"..." and path.stat().st_mode & 0o777 == 0o600
    assert out.stat().st_mode & 0o777 == 0o700
    assert not old.exists() and not old_side.exists() and keep.exists()
    assert seen["envs"][0]["PGPASSWORD"] == "pa@ss" and "PGPASSWORD" not in seen["envs"][1]
    # Children get only PATH, HOME, LANG and (pg_dump) PG* variables.
    assert seen["envs"][0] == {
        "PATH": "/usr/bin",
        "HOME": "/h",
        "LANG": "C",
        "PGSSLMODE": "require",
        "PGPASSWORD": "pa@ss",
    }
    assert seen["envs"][1] == {"PATH": "/usr/bin", "HOME": "/h", "LANG": "C"}
    side = backup.sidecar(path)
    assert side.stat().st_mode & 0o777 == 0o600
    assert backup.read_sidecar(path) == (backup.file_sha256(path), HEAD)
    assert side.read_text().splitlines()[0] == f"{backup.file_sha256(path)}  {path.name}"


def test_bad_head_is_refused(tmp_path):
    with pytest.raises(backup.BackupError, match="ledger head"):
        backup.backup(DSN, RECIPIENT, tmp_path / "b", {}, "7:zz\nx")


def _fake_backup(tmp_path, monkeypatch):
    monkeypatch.setattr(backup, "_pipe", lambda *a: a[4].write(backup.AGE_HEADER + b"payload"))
    return backup.backup(DSN, RECIPIENT, tmp_path / "b", {}, HEAD)


@pytest.mark.parametrize("damage", ["file", "sidecar", "missing", "malformed", "other-name"])
def test_restore_refuses_a_backup_that_does_not_match_its_checksum(tmp_path, monkeypatch, damage):
    """Adversarial: a corrupted or swapped backup never reaches age or pg_restore."""
    path = _fake_backup(tmp_path, monkeypatch)
    side = backup.sidecar(path)
    if damage == "file":
        path.write_bytes(path.read_bytes() + b"x")
    elif damage == "sidecar":
        side.write_text(f"{'0' * 64}  {path.name}\nledger-head {HEAD}\n")
    elif damage == "missing":
        side.unlink()
    elif damage == "malformed":
        side.write_text(f"{backup.file_sha256(path)}  {path.name}\n")
    else:
        side.write_text(f"{backup.file_sha256(path)}  pmx-x.dump.age\nledger-head {HEAD}\n")
    ran = []
    monkeypatch.setattr(backup, "_pipe", lambda *a: ran.append(a))
    with pytest.raises(backup.BackupError, match="checksum"):
        backup.restore(path, tmp_path / "id", DSN, {})
    assert ran == []


def test_restore_verifies_the_ledger_against_the_recorded_head(pg, pg_dsn, tmp_path, monkeypatch):
    pg.enqueue("bak00002", "bak:2", "c" * 64, "/tmp/x", {})
    head = db.ledger_head(pg.conn)
    monkeypatch.setattr(backup, "_pipe", lambda *a: a[4].write(backup.AGE_HEADER + b"payload"))
    path = backup.backup(pg_dsn, RECIPIENT, tmp_path / "b", {}, head)
    monkeypatch.setattr(backup, "_pipe", lambda *a: None)  # "restored" = the test database
    assert backup.restore(path, tmp_path / "id", pg_dsn, {})["problems"] == []
    # The restored ledger lost its tail (the anchored row): refused.
    with pg.conn.transaction():
        pg.conn.execute("ALTER TABLE ledger DISABLE TRIGGER ledger_no_update")
        pg.conn.execute("DELETE FROM ledger WHERE id = %s", (int(head.split(":")[0]),))
        pg.conn.execute("ALTER TABLE ledger ENABLE TRIGGER ledger_no_update")
    with pytest.raises(backup.BackupError, match="expected head row is gone"):
        backup.restore(path, tmp_path / "id", pg_dsn, {})


def test_unencrypted_output_is_refused_and_removed(tmp_path, monkeypatch):
    monkeypatch.setattr(backup, "_pipe", lambda *a: a[4].write(b"PGDMP plain dump"))
    with pytest.raises(backup.BackupError, match="not age-encrypted"):
        backup.backup(DSN, RECIPIENT, tmp_path / "b", {}, HEAD)
    assert list((tmp_path / "b").iterdir()) == []


def test_backup_dir_symlink_is_refused(tmp_path):
    (tmp_path / "real").mkdir()
    (tmp_path / "link").symlink_to(tmp_path / "real")
    with pytest.raises(backup.BackupError, match="symlink"):
        backup.backup(DSN, RECIPIENT, tmp_path / "link", {}, HEAD)


def _cli(tmp_path, *args):
    return cli_main(["--env-file", str(tmp_path / "none.env"), *args])


def test_restore_needs_yes(tmp_path, monkeypatch, capsys):
    called = []
    monkeypatch.setattr(backup, "restore", lambda *a: called.append(a) or {"rows": 3})
    f = tmp_path / "x.age"
    f.write_bytes(b"x")
    argv = ["restore", str(f), "--identity", str(tmp_path / "id"), "--target-dsn", DSN]
    assert _cli(tmp_path, *argv) == 4 and called == []
    assert "--yes" in capsys.readouterr().err
    assert _cli(tmp_path, *argv, "--yes") == 0 and len(called) == 1
    assert "pa@ss" not in capsys.readouterr().out


def test_backup_needs_a_recipient(pg, pg_dsn, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MIGRATE_DATABASE_URL", pg_dsn)
    monkeypatch.delenv("PARSEMAXXING_BACKUP_RECIPIENT", raising=False)
    pg.conn.execute("DELETE FROM settings_groups WHERE grp = 'backup'")
    assert _cli(tmp_path, "backup", "--out-dir", str(tmp_path / "b")) == 4
    assert "backup.age_recipient" in capsys.readouterr().err


TOOLS = ("age", "age-keygen", "pg_dump", "pg_restore")


@pytest.mark.skipif(
    not all(shutil.which(t) for t in TOOLS), reason="age or the PostgreSQL client is not on PATH"
)
def test_backup_and_restore_round_trip(pg, pg_dsn, tmp_path, monkeypatch, capsys):
    identity = tmp_path / "id.txt"
    subprocess.run(["age-keygen", "-o", str(identity)], check=True, capture_output=True)  # noqa: S603, S607
    recipient = subprocess.run(  # noqa: S603
        ["age-keygen", "-y", str(identity)],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    pg.enqueue("bak00001", "bak:1", "b" * 64, "/tmp/x", {})
    pg.event("bak00001", "log", {"line": "before backup"})
    monkeypatch.setenv("MIGRATE_DATABASE_URL", pg_dsn)
    monkeypatch.setenv("PARSEMAXXING_BACKUP_RECIPIENT", recipient)
    assert _cli(tmp_path, "backup", "--out-dir", str(tmp_path / "b")) == 0
    path, side = sorted((tmp_path / "b").iterdir())
    assert side == backup.sidecar(path)
    assert backup.read_sidecar(path)[1] == db.ledger_head(pg.conn)
    assert b"before backup" not in path.read_bytes()  # encrypted

    admin = urlunsplit(urlsplit(pg_dsn)._replace(path="/postgres"))
    target = urlunsplit(urlsplit(pg_dsn)._replace(path="/parsemaxxing_restore_test"))
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute("DROP DATABASE IF EXISTS parsemaxxing_restore_test WITH (FORCE)")
        conn.execute("CREATE DATABASE parsemaxxing_restore_test")
    try:
        argv = ["restore", str(path), "--identity", str(identity), "--target-dsn", target]
        assert _cli(tmp_path, *argv, "--yes") == 0
        with db.connect(target) as conn:
            assert db.Store(conn).get("bak00001")["status"] == "queued"
            assert db.verify_ledger(conn)["problems"] == []
        secret_key = identity.read_text().splitlines()[-1]
        assert secret_key not in capsys.readouterr().out
    finally:
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute("DROP DATABASE IF EXISTS parsemaxxing_restore_test WITH (FORCE)")
