"""Encrypted database backups (design 7.5 "Backups"): `pg_dump` piped to `age`, restore piped
back to `pg_restore`.

The dump is encrypted to an age public key (settings `backup.age_recipient`); the private key
(identity) stays off the server and is passed only to a restore. The database password goes to
the child processes as PGPASSWORD, never on a command line, and nothing here logs it or the
identity. Backups older than RETENTION_DAYS are pruned at each backup (design 7.19).
"""

import os
import re

# Fixed argument lists for pg_dump, pg_restore and age only.
import subprocess  # nosec B404
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from psycopg.conninfo import conninfo_to_dict, make_conninfo

RETENTION_DAYS = 30
TIMEOUT_S = 3600
AGE_HEADER = b"age-encryption.org/v1"
NAME = re.compile(r"pmx-\d{8}T\d{6}Z\.dump\.age")


class BackupError(RuntimeError):
    """A refused or failed backup or restore. Messages never contain passwords or keys."""


def split_dsn(dsn: str) -> tuple[str, dict[str, str]]:
    """The connection string without its password, and the password as child environment."""
    params = conninfo_to_dict(dsn)
    password = params.pop("password", None)
    return make_conninfo(**params), ({"PGPASSWORD": str(password)} if password else {})


def dump_argv(conninfo: str) -> list[str]:
    return ["pg_dump", "--format=custom", "--no-owner", "--dbname", conninfo]


def restore_argv(conninfo: str) -> list[str]:
    return [
        "pg_restore",
        "--clean",
        "--if-exists",
        "--no-owner",
        "--exit-on-error",
        "--single-transaction",
        "--dbname",
        conninfo,
    ]


def encrypt_argv(recipient: str) -> list[str]:
    if not re.fullmatch(r"age1[02-9ac-hj-np-z]{58}", recipient):  # bech32
        raise BackupError("the backup recipient must be an age public key (age1...)")
    return ["age", "--encrypt", "--recipient", recipient]


def decrypt_argv(identity: Path) -> list[str]:
    return ["age", "--decrypt", "--identity", str(identity)]


def _pipe(first: list[str], second: list[str], envs: tuple[dict, dict], stdin, stdout) -> None:
    """first | second, both with timeouts; any non-zero exit fails the whole pipe."""
    p1 = subprocess.Popen(first, stdin=stdin, stdout=subprocess.PIPE, env=envs[0])  # noqa: S603  # nosec B603
    try:
        p2 = subprocess.Popen(second, stdin=p1.stdout, stdout=stdout, env=envs[1])  # noqa: S603  # nosec B603
    except OSError:
        p1.kill()
        raise
    p1.stdout.close()  # type: ignore[union-attr]  # so `first` sees a closed pipe if `second` dies
    try:
        codes = (p2.wait(TIMEOUT_S), p1.wait(TIMEOUT_S))
    except subprocess.TimeoutExpired:
        p1.kill()
        p2.kill()
        raise BackupError(f"{first[0]} | {second[0]} timed out") from None
    if any(codes):
        raise BackupError(f"{first[0]} | {second[0]} failed (exit {codes[1]}, {codes[0]})")


def backup(dsn: str, recipient: str, out_dir: Path, environ: Mapping[str, str]) -> Path:
    """Write out_dir/pmx-<UTC time>.dump.age (folder 0700, file 0600) and prune old backups."""
    age = encrypt_argv(recipient)
    if out_dir.is_symlink():
        raise BackupError("the backup folder must not be a symlink")
    out_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    out_dir.chmod(0o700)
    path = out_dir / f"pmx-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.dump.age"
    conninfo, secret = split_dsn(dsn)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as out:
            _pipe(dump_argv(conninfo), age, ({**environ, **secret}, dict(environ)), None, out)
        with path.open("rb") as f:
            if f.read(len(AGE_HEADER)) != AGE_HEADER:
                raise BackupError("the backup output is not age-encrypted")
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    prune(out_dir)
    return path


def prune(out_dir: Path, days: int = RETENTION_DAYS) -> list[Path]:
    """Remove this tool's backups older than `days` (only names it writes)."""
    cutoff = time.time() - days * 86400
    gone = []
    for p in out_dir.iterdir():
        if NAME.fullmatch(p.name) and not p.is_symlink() and p.stat().st_mtime < cutoff:
            p.unlink()
            gone.append(p)
    return gone


def restore(file: Path, identity: Path, dsn: str, environ: Mapping[str, str]) -> None:
    """Decrypt `file` with the age identity and restore it into the database `dsn` (replacing
    the objects it contains, in one transaction)."""
    if not file.is_file() or file.is_symlink():
        raise BackupError("no such backup file")
    conninfo, secret = split_dsn(dsn)
    with file.open("rb") as src:
        _pipe(
            decrypt_argv(identity),
            restore_argv(conninfo),
            (dict(environ), {**environ, **secret}),
            src,
            subprocess.DEVNULL,
        )
