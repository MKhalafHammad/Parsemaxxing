"""The secrets vault (design 7.5): AES-256-GCM envelope encryption with `cryptography` only.

Each secret value is encrypted under its own random 256-bit data key (DEK) with a random 96-bit
nonce; the DEK is encrypted ("wrapped") under the KEK with another random nonce. Both AADs bind
the secret's id, scope, name and version, so a ciphertext or wrapped key copied into another row
fails authentication. Every failure is fail-closed and its message never contains a value.
"""

import base64
import binascii
import hashlib
import hmac
import json
import os
import re
import stat
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import psycopg
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from parsemaxxing.settings.model import Scope

KEK_ENV = "PARSEMAXXING_KEK_FILE"
DEFAULT_KEK_FILE = Path("/run/secrets/pmx_kek")
NONCE_BYTES = 12
NAME = re.compile(r"[a-z][a-z0-9_.:-]{0,127}")


class VaultError(RuntimeError):
    """A refused vault operation. Never carries a secret value or key material."""


def kek_file(environ: Mapping[str, str]) -> Path:
    """The KEK path from the bootstrap environment (passed in; this module never reads it)."""
    return Path(environ.get(KEK_ENV) or DEFAULT_KEK_FILE)


class Kek:
    """The key-encryption key. Holds the key only inside an AESGCM object; repr is redacted."""

    __slots__ = ("_aead", "id")

    def __init__(self, key: bytes):
        if len(key) != 32:
            raise VaultError("the KEK must be 32 bytes")
        self._aead = AESGCM(key)
        # Public fingerprint: HMAC under the key, so it reveals nothing about the key.
        self.id = hmac.new(key, b"parsemaxxing kek id", hashlib.sha256).hexdigest()[:32]

    @classmethod
    def load(cls, path: Path) -> "Kek":
        """Read a KEK file: one line, 32 random bytes in base64, readable by its owner only."""
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        except OSError as e:
            raise VaultError(f"cannot open the KEK file {path} ({e.strerror})") from None
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode):
                raise VaultError(f"the KEK file {path} is not a regular file")
            if st.st_mode & 0o077:
                raise VaultError(
                    f"the KEK file {path} is readable by group or others "
                    f"(mode {stat.S_IMODE(st.st_mode):04o}); chmod 0400 it"
                )
            data = os.read(fd, 1024)
        finally:
            os.close(fd)
        try:
            key = base64.b64decode(data.removesuffix(b"\n"), validate=True)
        except (binascii.Error, ValueError):
            raise VaultError(f"the KEK file {path} is not one line of base64") from None
        if len(key) != 32:
            raise VaultError(f"the KEK file {path} must hold 32 bytes (base64 of 32 random bytes)")
        return cls(key)

    def __repr__(self) -> str:
        return f"Kek(id={self.id})"

    __str__ = __repr__

    def __reduce__(self):
        raise TypeError("a KEK cannot be pickled")


class Plaintext:
    """A decrypted value, valid only inside `Vault.use`. Redacted in repr, str and f-strings;
    the buffer is overwritten when the block ends (best effort: Python may hold other copies)."""

    __slots__ = ("_buf",)

    def __init__(self, value: bytes):
        self._buf: bytearray | None = bytearray(value)

    def reveal(self) -> bytes:
        if self._buf is None:
            raise VaultError("a secret is only usable inside its `with vault.use(...)` block")
        return bytes(self._buf)

    def text(self) -> str:
        return self.reveal().decode("utf-8")

    def _wipe(self) -> None:
        if self._buf is not None:
            self._buf[:] = bytes(len(self._buf))
            self._buf = None

    def __repr__(self) -> str:
        return "Plaintext(<redacted>)"

    __str__ = __repr__

    def __reduce__(self):
        raise TypeError("a secret cannot be pickled")


@dataclass(frozen=True)
class SecretInfo:
    """What the API may show about a secret: never the value."""

    id: str
    scope: Scope
    name: str
    version: int
    updated_at: datetime
    updated_by: str


def _aad(kind: bytes, secret_id: str, scope: Scope, name: str, version: int) -> bytes:
    fields = [secret_id, scope.environment, scope.client, name, version]
    return b"parsemaxxing-vault/1\x00" + kind + b"\x00" + json.dumps(fields).encode()


def _seal(kek: Kek, secret_id: str, scope: Scope, name: str, version: int, value: bytes) -> dict:
    dek = AESGCM.generate_key(bit_length=256)
    nonce, dek_nonce = os.urandom(NONCE_BYTES), os.urandom(NONCE_BYTES)
    return {
        "nonce": nonce,
        "ciphertext": AESGCM(dek).encrypt(
            nonce, value, _aad(b"data", secret_id, scope, name, version)
        ),
        "dek_nonce": dek_nonce,
        "wrapped_dek": kek._aead.encrypt(
            dek_nonce, dek, _aad(b"dek", secret_id, scope, name, version)
        ),
    }


def _unwrap(kek: Kek, row: dict) -> bytes:
    scope = Scope(row["environment"], row["client"])
    aad = _aad(b"dek", str(row["id"]), scope, row["name"], row["version"])
    try:
        return kek._aead.decrypt(bytes(row["dek_nonce"]), bytes(row["wrapped_dek"]), aad)
    except InvalidTag:
        raise VaultError(
            f"secret {row['id']} failed authentication (wrong KEK or altered row)"
        ) from None


def _open(kek: Kek, row: dict) -> bytes:
    dek = _unwrap(kek, row)
    scope = Scope(row["environment"], row["client"])
    aad = _aad(b"data", str(row["id"]), scope, row["name"], row["version"])
    try:
        return AESGCM(dek).decrypt(bytes(row["nonce"]), bytes(row["ciphertext"]), aad)
    except InvalidTag:
        raise VaultError(f"secret {row['id']} failed authentication (altered row)") from None


_KEK_QUERY = {
    "": "SELECT kek_id FROM vault_kek",
    "FOR SHARE": "SELECT kek_id FROM vault_kek FOR SHARE",
    "FOR UPDATE": "SELECT kek_id FROM vault_kek FOR UPDATE",
}


def _check_kek(conn: psycopg.Connection, kek: Kek, lock: str) -> None:
    """Refuse a KEK other than the one the vault is wrapped with; record it on first use."""
    row = conn.execute(_KEK_QUERY[lock]).fetchone()
    if row is None:
        conn.execute("INSERT INTO vault_kek (kek_id) VALUES (%s)", (kek.id,))
    elif not hmac.compare_digest(row["kek_id"], kek.id):
        raise VaultError("this KEK is not the vault's KEK (wrong file, or rotated elsewhere)")


class Vault:
    """`conn`: an autocommit psycopg connection with dict rows (ledger.store.connect)."""

    def __init__(self, conn: psycopg.Connection, kek: Kek):
        self.conn = conn
        self.kek = kek

    def __repr__(self) -> str:
        return f"Vault(kek={self.kek.id})"

    def put(self, scope: Scope, name: str, value: str | bytes, actor: str) -> str:
        """Create or replace the secret `name` in `scope` (new version, new DEK). Returns its id."""
        if not NAME.fullmatch(name):
            raise VaultError("secret names match [a-z][a-z0-9_.:-]{0,127}")
        raw = value.encode("utf-8") if isinstance(value, str) else bytes(value)
        if not raw:
            raise VaultError("an empty secret is refused")
        with self.conn.transaction():
            _check_kek(self.conn, self.kek, "FOR SHARE")
            row = self.conn.execute(
                "SELECT id, version FROM secrets WHERE environment = %s AND client = %s"
                " AND name = %s FOR UPDATE",
                (scope.environment, scope.client, name),
            ).fetchone()
            if row is None:
                secret_id, version = str(uuid.uuid4()), 1
                sealed = _seal(self.kek, secret_id, scope, name, version, raw)
                self.conn.execute(
                    "INSERT INTO secrets (id, environment, client, name, version, dek_nonce,"
                    " wrapped_dek, nonce, ciphertext, updated_by)"
                    " VALUES (%s, %s, %s, %s, 1, %s, %s, %s, %s, %s)",
                    (
                        secret_id,
                        scope.environment,
                        scope.client,
                        name,
                        sealed["dek_nonce"],
                        sealed["wrapped_dek"],
                        sealed["nonce"],
                        sealed["ciphertext"],
                        actor,
                    ),
                )
            else:
                secret_id, version = str(row["id"]), row["version"] + 1
                sealed = _seal(self.kek, secret_id, scope, name, version, raw)
                cur = self.conn.execute(
                    "UPDATE secrets SET version = %s, dek_nonce = %s, wrapped_dek = %s,"
                    " nonce = %s, ciphertext = %s, updated_by = %s, updated_at = now()"
                    " WHERE id = %s AND version = %s",
                    (
                        version,
                        sealed["dek_nonce"],
                        sealed["wrapped_dek"],
                        sealed["nonce"],
                        sealed["ciphertext"],
                        actor,
                        secret_id,
                        row["version"],
                    ),
                )
                if cur.rowcount != 1:
                    raise VaultError(f"secret {secret_id} changed concurrently")
            _audit(self.conn, actor, scope, name, "secret_changed")
        return secret_id

    @contextmanager
    def use(self, secret_id: str, scope: Scope) -> Iterator[Plaintext]:
        """`with vault.use(id, scope) as p: p.text()`: decrypted only inside the block, and only
        if the secret belongs to exactly this scope."""
        row = self._row(secret_id, scope)
        _check_kek(self.conn, self.kek, "")
        value = Plaintext(_open(self.kek, row))
        try:
            yield value
        finally:
            value._wipe()

    def info(self, secret_id: str, scope: Scope) -> SecretInfo:
        row = self._row(secret_id, scope)
        return SecretInfo(
            str(row["id"]), scope, row["name"], row["version"], row["updated_at"], row["updated_by"]
        )

    def list(self, scope: Scope) -> list[SecretInfo]:
        rows = self.conn.execute(
            "SELECT id, name, version, updated_at, updated_by FROM secrets"
            " WHERE environment = %s AND client = %s ORDER BY name",
            (scope.environment, scope.client),
        ).fetchall()
        return [
            SecretInfo(
                str(r["id"]), scope, r["name"], r["version"], r["updated_at"], r["updated_by"]
            )
            for r in rows
        ]

    def _row(self, secret_id: str, scope: Scope) -> dict:
        try:
            uuid.UUID(str(secret_id))
        except ValueError:
            raise VaultError("no such secret in this scope") from None
        row = self.conn.execute(
            "SELECT * FROM secrets WHERE id = %s AND environment = %s AND client = %s",
            (str(secret_id), scope.environment, scope.client),
        ).fetchone()
        if row is None:  # another scope's secret is indistinguishable from a missing one
            raise VaultError("no such secret in this scope")
        return row


def rotate_kek(conn: psycopg.Connection, old: Kek, new: Kek, actor: str) -> int:
    """Rewrap every DEK from `old` to `new` in one transaction; returns the number of secrets.
    Values, nonces and versions are unchanged. Any failure rolls the whole rotation back."""
    if hmac.compare_digest(old.id, new.id):
        raise VaultError("the new KEK is the current KEK")
    with conn.transaction():
        _check_kek(conn, old, "FOR UPDATE")
        conn.execute("LOCK TABLE secrets IN EXCLUSIVE MODE")  # no write with the old KEK meanwhile
        rows = conn.execute(
            "SELECT id, environment, client, name, version, dek_nonce, wrapped_dek FROM secrets"
            " ORDER BY id"
        ).fetchall()
        for row in rows:
            scope = Scope(row["environment"], row["client"])
            aad = _aad(b"dek", str(row["id"]), scope, row["name"], row["version"])
            dek = _unwrap(old, row)
            dek_nonce = os.urandom(NONCE_BYTES)
            wrapped = new._aead.encrypt(dek_nonce, dek, aad)
            if new._aead.decrypt(dek_nonce, wrapped, aad) != dek:  # pragma: no cover - paranoia
                raise VaultError("rewrap check failed")
            cur = conn.execute(
                "UPDATE secrets SET dek_nonce = %s, wrapped_dek = %s"
                " WHERE id = %s AND version = %s",
                (dek_nonce, wrapped, row["id"], row["version"]),
            )
            if cur.rowcount != 1:
                raise VaultError(f"secret {row['id']} changed during rotation")
        conn.execute(
            "INSERT INTO vault_kek (kek_id) VALUES (%s)"
            " ON CONFLICT (one) DO UPDATE SET kek_id = EXCLUDED.kek_id, rotated_at = now()",
            (new.id,),
        )
        _audit(conn, actor, Scope(), "kek", "kek_rotated")
    return len(rows)


def _audit(conn: psycopg.Connection, actor: str, scope: Scope, name: str, action: str) -> None:
    conn.execute(
        "INSERT INTO settings_history (actor, environment, client, grp, field, action, redacted)"
        " VALUES (%s, %s, %s, 'vault', %s, %s, true)",
        (actor, scope.environment, scope.client, name, action),
    )
