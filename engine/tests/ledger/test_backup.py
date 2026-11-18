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
        backup.backup(DSN, bad, tmp_path / "b", {})
    assert not (tmp_path / "b").exists()


def test_failed_pipe_leaves_no_partial_file(tmp_path, monkeypatch):
    def fail(*a, **k):
        raise backup.BackupError("pg_dump | age failed")

    monkeypatch.setattr(backup, "_pipe", fail)
    with pytest.raises(backup.BackupError):
        backup.backup(DSN, RECIPIENT, tmp_path / "b", {})
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
    path = backup.backup(DSN, RECIPIENT, out, {"PATH": "/usr/bin"})
    assert path.read_bytes() == backup.AGE_HEADER + b"..." and path.stat().st_mode & 0o777 == 0o600
    assert out.stat().st_mode & 0o777 == 0o700
    assert not old.exists() and keep.exists()
    assert seen["envs"][0]["PGPASSWORD"] == "pa@ss" and "PGPASSWORD" not in seen["envs"][1]


def test_unencrypted_output_is_refused_and_removed(tmp_path, monkeypatch):
    monkeypatch.setattr(backup, "_pipe", lambda *a: a[4].write(b"PGDMP plain dump"))
    with pytest.raises(backup.BackupError, match="not age-encrypted"):
        backup.backup(DSN, RECIPIENT, tmp_path / "b", {})
    assert list((tmp_path / "b").iterdir()) == []


def test_backup_dir_symlink_is_refused(tmp_path):
    (tmp_path / "real").mkdir()
    (tmp_path / "link").symlink_to(tmp_path / "real")
    with pytest.raises(backup.BackupError, match="symlink"):
        backup.backup(DSN, RECIPIENT, tmp_path / "link", {})


def _cli(tmp_path, *args):
    return cli_main(["--env-file", str(tmp_path / "none.env"), *args])


def test_restore_needs_yes(tmp_path, monkeypatch, capsys):
    called = []
    monkeypatch.setattr(backup, "restore", lambda *a: called.append(a))
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
    (path,) = (tmp_path / "b").iterdir()
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
