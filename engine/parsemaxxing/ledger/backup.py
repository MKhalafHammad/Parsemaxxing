"""Encrypted database backups (design 7.5 "Backups"): `pg_dump` piped to `age`, restore piped
back to `pg_restore`.

The dump is encrypted to an age public key (settings `backup.age_recipient`); the private key
(identity) stays off the server and is passed only to a restore. The database password goes to
the child processes as PGPASSWORD, never on a command line, and nothing here logs it or the
identity. Backups older than RETENTION_DAYS are pruned at each backup (design 7.19).

Beside each backup, `<backup>.sha256` (0600) holds the SHA-256 of the encrypted file and the
ledger head at backup time:

    <64 hex>  pmx-<time>.dump.age
    ledger-head <id>:<hash>

A restore checks the file against it before decrypting, then verifies the restored ledger chain
with that head as anchor. Child processes get only PATH, HOME, LANG and (pg_*) PG* variables.
"""

import hashlib
import hmac
import os
import re

# Fixed argument lists for pg_dump, pg_restore and age only.
import subprocess  # nosec B404
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from psycopg.conninfo import conninfo_to_dict, make_conninfo

from parsemaxxing.ledger import store as db

RETENTION_DAYS = 30
TIMEOUT_S = 3600
AGE_HEADER = b"age-encryption.org/v1"
NAME = re.compile(r"pmx-\d{8}T\d{6}Z\.dump\.age")


class BackupError(RuntimeError):
    """A refused or failed backup or restore. Messages never contain passwords or keys."""


def child_env(environ: Mapping[str, str], pg: bool) -> dict[str, str]:
    """Only what pg_dump, pg_restore and age need: never the engine's other variables."""
    return {
        k: v
        for k, v in environ.items()
        if k in ("PATH", "HOME", "LANG") or (pg and k.startswith("PG"))
    }


def sidecar(path: Path) -> Path:
    return path.with_name(path.name + ".sha256")


def file_sha256(path: Path) -> str:
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def read_sidecar(path: Path) -> tuple[str, str]:
    """(sha256, ledger head) from `<backup>.sha256`; BackupError if missing or malformed."""
    side = sidecar(path)
    if not side.is_file() or side.is_symlink():
        raise BackupError(f"no checksum file {side.name} beside the backup")
    lines = side.read_text(encoding="ascii", errors="replace").splitlines()
    m1 = re.fullmatch(r"([0-9a-f]{64})  (\S+)", lines[0]) if len(lines) == 2 else None
    m2 = re.fullmatch(r"ledger-head (\S+)", lines[1]) if m1 else None
    if not m2 or m1[2] != path.name or not db.HEAD.fullmatch(m2[1]):
        raise BackupError(f"the checksum file {side.name} is malformed")
    return m1[1], m2[1]


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


def backup(dsn: str, recipient: str, out_dir: Path, environ: Mapping[str, str], head: str) -> Path:
    """Write out_dir/pmx-<UTC time>.dump.age and its .sha256 (folder 0700, files 0600) and prune
    old backups. `head`: the ledger head (`store.ledger_head`) read before the dump starts, so
    the dump contains that row."""
    age = encrypt_argv(recipient)
    if not db.HEAD.fullmatch(head):
        raise BackupError("the ledger head is <id>:<hash>")
    if out_dir.is_symlink():
        raise BackupError("the backup folder must not be a symlink")
    out_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    out_dir.chmod(0o700)
    path = out_dir / f"pmx-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.dump.age"
    conninfo, secret = split_dsn(dsn)
    envs = ({**child_env(environ, pg=True), **secret}, child_env(environ, pg=False))
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, "wb") as out:
            _pipe(dump_argv(conninfo), age, envs, None, out)
        with path.open("rb") as f:
            if f.read(len(AGE_HEADER)) != AGE_HEADER:
                raise BackupError("the backup output is not age-encrypted")
        with os.fdopen(os.open(sidecar(path), flags, 0o600), "w", encoding="ascii") as side:
            side.write(f"{file_sha256(path)}  {path.name}\nledger-head {head}\n")
    except BaseException:
        path.unlink(missing_ok=True)
        sidecar(path).unlink(missing_ok=True)
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
            sidecar(p).unlink(missing_ok=True)
            gone.append(p)
    return gone


def restore(file: Path, identity: Path, dsn: str, environ: Mapping[str, str]) -> dict:
    """Check `file` against its .sha256, decrypt it with the age identity, restore it into the
    database `dsn` (replacing the objects it contains, in one transaction), then verify the
    restored ledger chain anchored at the recorded head. Returns the verify result."""
    if not file.is_file() or file.is_symlink():
        raise BackupError("no such backup file")
    expected, head = read_sidecar(file)
    if not hmac.compare_digest(file_sha256(file), expected):
        raise BackupError("the backup file does not match its checksum; nothing was restored")
    conninfo, secret = split_dsn(dsn)
    with file.open("rb") as src:
        _pipe(
            decrypt_argv(identity),
            restore_argv(conninfo),
            (child_env(environ, pg=False), {**child_env(environ, pg=True), **secret}),
            src,
            subprocess.DEVNULL,
        )
    with db.connect(dsn) as conn:
        result = db.verify_ledger(conn, expect_head=head)
    if result["problems"]:
        first = result["problems"][0]
        raise BackupError(
            f"restored, but the ledger fails verification against head {head}"
            f" (row {first['id']}: {first['problem']}); run `parsemaxxing ledger verify`"
        )
    return result
