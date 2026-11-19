"""Local accounts, sessions, MFA, API tokens, lockout and the setup token (design 7.3).

`conn` is an autocommit psycopg connection with dict rows (ledger.store.connect). Every
credential is stored as a hash (Argon2id for passwords, SHA-256 for 256-bit random values);
TOTP secrets live in the vault. Failures raise AuthError with a message for the user.

Directory (LDAP) users (design 7.4) sign in with the same form: a name that is not a local
account goes to the directory when LDAP is on. They get a local row (source 'ldap', no password
hash) so sessions, MFA, audit and created_by work; the role is re-read from their groups at
every sign-in. Local accounts never touch the directory, so they work while it is down.
"""

import asyncio
import hashlib
import hmac
import math
import os
import re
import secrets
import time
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from functools import cached_property
from pathlib import Path

import psycopg
import pyotp

from parsemaxxing.auth import events, passwords
from parsemaxxing.auth.ldap import (
    Connect,
    Directory,
    DirectoryRefused,
    DirectoryUnavailable,
    DirectoryUser,
)
from parsemaxxing.auth.model import AuthError, Principal, Role, Stage
from parsemaxxing.secrets import Kek, Vault, VaultError
from parsemaxxing.settings import PLATFORM, AuthSettings, LdapSettings, SettingsService

LOGIN_FAILED = "Sign-in failed. Check your user name and password."
SETUP_INVALID = (
    "This setup token is not valid. Tokens expire 60 minutes after the engine starts;"
    " restart the engine to get a new one."
)
USERNAME = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
TOKEN = re.compile(r"pmxt_[A-Za-z0-9_-]{43}")
TOKEN_MAX_DAYS = 90
PENDING_SECONDS = 15 * 60  # a session that still owes MFA (or enrolment)
SETUP_MINUTES = 60
RECOVERY_CODES = 10
RECOVERY_ALPHABET = "abcdefghijkmnpqrstuvwxyz23456789"  # 32 symbols, no 0/o, 1/l
ADMIN_LOCK = 7004  # advisory lock: setup and changes that could remove the last admin
TOTP_ISSUER = "Parsemaxxing"


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _key(kind: str, value: str) -> str:
    return sha256(f"{kind}:{value}")


def _wait_text(seconds: int) -> str:
    minutes = max(1, math.ceil(seconds / 60))
    return f"Too many attempts. Try again in {minutes} minute{'s' if minutes > 1 else ''}."


def _sleep(seconds: float) -> None:  # tests replace both (engine/tests/conftest.py)
    time.sleep(seconds)


async def _asleep(seconds: float) -> None:
    await asyncio.sleep(seconds)


def _pad(started: float, minimum: float) -> None:
    """Hold a failed sign-in until `minimum` seconds after it started: local and directory
    names, and each directory failure step, then take the same time from outside."""
    if (left := minimum - (time.monotonic() - started)) > 0:
        _sleep(left)


async def pad_failure(e: AuthError) -> None:
    """The API's padding: waits on the event loop, so a failed sign-in holds no worker thread
    (a blocking sleep would let concurrent failures stall every other request)."""
    if e.pad_until and (left := e.pad_until - time.monotonic()) > 0:
        await _asleep(left)


def admin_exists(conn: psycopg.Connection) -> bool:
    return conn.execute("SELECT 1 FROM users WHERE role = 'admin' LIMIT 1").fetchone() is not None


def _read_token_file(path: Path) -> str:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return ""
    with os.fdopen(fd, encoding="utf-8") as f:
        return f.read(256).strip()


def issue_setup_token(
    conn: psycopg.Connection, path: Path, actor: str = "engine", force: bool = False
) -> str | None:
    """While no admin exists: the one-time setup token (60 minutes, single use) in `path`
    (mode 0600). Idempotent across engine workers: an unexpired, unused token whose file is
    present is kept; `force` (the CLI) replaces it. Returns the token, or None when setup is
    done."""
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (ADMIN_LOCK,))
        if admin_exists(conn):
            return None
        if not force:
            row = conn.execute(
                "SELECT token_hash FROM setup_token WHERE used_at IS NULL AND expires_at > now()"
            ).fetchone()
            kept = _read_token_file(path)
            if row and kept and hmac.compare_digest(row["token_hash"], sha256(kept)):
                return kept
        raw = secrets.token_urlsafe(32)
        path.unlink(missing_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(raw + "\n")
        conn.execute(
            "INSERT INTO setup_token (one, token_hash, expires_at)"
            " VALUES (true, %s, now() + make_interval(mins => %s)) ON CONFLICT (one) DO UPDATE"
            " SET token_hash = EXCLUDED.token_hash, issued_at = now(),"
            " expires_at = EXCLUDED.expires_at, used_at = NULL",
            (sha256(raw), SETUP_MINUTES),
        )
        events.record(conn, "setup_token_issued", "success", actor)
    return raw


def public_user(row: dict) -> dict:
    return {
        "id": str(row["id"]),
        "username": row["username"],
        "display_name": row["display_name"],
        "role": row["role"],
        "source": row["source"],
        "mfa": bool(row.get("mfa")),
        "disabled": row["disabled_at"] is not None,
        "last_login_at": str(row["last_login_at"]) if row.get("last_login_at") else None,
        "created_at": str(row["created_at"]),
    }


class Auth:
    ldap_connect: Connect | None = None  # tests replace the directory transport (MOCK_SYNC)

    def __init__(
        self,
        conn: psycopg.Connection,
        settings: AuthSettings,
        kek: Callable[[], Kek] | None = None,
        environ: Mapping[str, str] | None = None,
    ):
        self.conn, self.s, self._kek = conn, settings, kek
        self._environ = dict(environ or {})

    @cached_property
    def ldap(self) -> LdapSettings:
        """Read only on the paths that need it (sign-in, account checks), not per request."""
        return SettingsService(self.conn, self._environ).get(LdapSettings, PLATFORM)

    def audit(self, event: str, outcome: str, actor: str, user_id=None, ip="", **detail) -> None:
        events.record(
            self.conn, event, outcome, actor, str(user_id) if user_id else None, ip, **detail
        )

    # --- lockout with exponential backoff ------------------------------------------------

    def throttle_wait(self, *keys: str) -> int:
        row = self.conn.execute(
            "SELECT ceil(extract(epoch FROM max(locked_until) - now()))::int AS wait"
            " FROM auth_throttle WHERE key = ANY(%s) AND locked_until > now()",
            (list(keys),),
        ).fetchone()
        return int(row["wait"] or 0) if row else 0

    def fail(self, key: str, threshold: int) -> int:
        """Count a failure; returns the lock in seconds when this failure starts one."""
        n = self.conn.execute(
            "INSERT INTO auth_throttle (key, failures) VALUES (%s, 1) ON CONFLICT (key) DO UPDATE"
            " SET failures = CASE WHEN auth_throttle.updated_at < now() - interval '1 hour'"
            " THEN 1 ELSE auth_throttle.failures + 1 END, updated_at = now() RETURNING failures",
            (key,),
        ).fetchone()["failures"]
        if n < threshold:
            return 0
        wait = min(
            self.s.lockout_base_seconds * 2 ** min(n - threshold, 20), self.s.lockout_max_seconds
        )
        self.conn.execute(
            "UPDATE auth_throttle SET locked_until = now() + make_interval(secs => %s)"
            " WHERE key = %s",
            (wait, key),
        )
        return wait

    def clear(self, key: str) -> None:
        self.conn.execute("DELETE FROM auth_throttle WHERE key = %s", (key,))

    def _refuse_if_locked(self, *keys: str) -> None:
        if wait := self.throttle_wait(*keys):
            raise AuthError(429, _wait_text(wait), wait)

    # --- login ---------------------------------------------------------------------------

    def login(
        self, username: str, password: str, ip: str, ua: str, pad: bool = True
    ) -> tuple[str, dict, Stage]:
        """Password step. Returns (session value, user, stage). Unknown, disabled and wrong
        password are one failure: same message, same Argon2 work, same lockout, same minimum
        time. `pad=False` (the async API route): the failure carries `pad_until` and the
        caller waits with `pad_failure` instead of sleeping here."""
        name = username.strip().lower()
        keys = (_key("user", name), _key("ip", ip))
        try:
            self._refuse_if_locked(*keys)
        except AuthError:
            self.audit("login", "refused", "anonymous", ip=ip, reason="locked")
            raise
        started = time.monotonic()
        try:
            user = self.conn.execute("SELECT * FROM users WHERE username = %s", (name,)).fetchone()
            if (user is None or user["source"] == "ldap") and self.ldap.enabled:
                user = self._directory_login(name, password, ip, keys)
            else:
                ok = passwords.verify(user["password_hash"] if user else None, password)
                if not ok or user["disabled_at"] is not None:
                    self._login_failed(keys, user, ip)
        except AuthError as e:
            if e.status == 401:  # every failed sign-in takes at least the same time (L1)
                e.pad_until = started + self.s.failure_min_seconds
                if pad:
                    _pad(started, self.s.failure_min_seconds)
            raise
        self.clear(keys[0])
        if user["password_hash"] and passwords.needs_rehash(user["password_hash"]):
            self.conn.execute(
                "UPDATE users SET password_hash = %s, updated_at = now() WHERE id = %s",
                (passwords.hash_password(password), user["id"]),
            )
        self.conn.execute("UPDATE users SET last_login_at = now() WHERE id = %s", (user["id"],))
        stage = self._stage_after_password(user)
        raw = self.new_session(user["id"], stage, ip, ua)
        self.audit("login", "success", user["username"], user["id"], ip, stage=stage)
        return raw, user, stage

    def _login_failed(
        self, keys: tuple[str, str], user: dict | None, ip: str, extra: str | None = None, **detail
    ) -> None:
        locked = max(
            self.fail(keys[0], self.s.lockout_threshold),
            self.fail(keys[1], self.s.ip_lockout_threshold),
            self.fail(extra, self.s.lockout_threshold) if extra else 0,
        )
        who = user["username"] if user else "anonymous"
        self.audit("login", "failure", who, user and user["id"], ip, **detail)
        if locked:
            self.audit("lockout", "refused", who, user and user["id"], ip, seconds=locked)
        raise AuthError(401, LOGIN_FAILED)

    # --- directory (LDAP) users ----------------------------------------------------------

    @contextmanager
    def directory(self) -> Iterator[Directory]:
        """A Directory holding the bind password and CA bundle only inside this block."""
        s = self.ldap
        if not (s.bind_password and s.ca_bundle):
            raise DirectoryUnavailable("not_configured")
        try:
            vault = Vault(self.conn, self._kek()) if self._kek else None
            if vault is None:
                raise VaultError("no KEK")
            with vault.use(s.bind_password, PLATFORM) as pw, vault.use(s.ca_bundle, PLATFORM) as ca:
                yield Directory(s, pw.text(), ca.text(), self.ldap_connect)
        except VaultError:
            raise DirectoryUnavailable("vault") from None

    def _directory_login(self, name: str, password: str, ip: str, keys: tuple[str, str]) -> dict:
        """Same failure message as a local login; the reason goes to the audit row only.
        Failures also count against the entry's stable identity (L5: one account reached
        through several typed names locks once). A directory outage is not counted towards
        lockout: shared client IPs would otherwise lock out the local break-glass admins too
        (T12.6). Argon2 work is done here as well, and `login` pads every failure (L1)."""
        passwords.verify(None, password)

        def unlocked(identity: str) -> None:  # before the user bind: no guess reaches it
            if self.throttle_wait(_key("dir", identity)):
                raise DirectoryRefused("locked", identity)

        try:
            with self.directory() as d:
                found = d.authenticate(name, password, unlocked)
        except DirectoryUnavailable as e:
            self.audit("login", "failure", "anonymous", ip=ip, source="ldap", reason=e.reason)
            raise AuthError(401, LOGIN_FAILED) from None
        except DirectoryRefused as e:
            extra = _key("dir", e.identity) if e.identity else None
            self._login_failed(keys, None, ip, extra, source="ldap", reason=e.reason)
        dir_key = _key("dir", found.identity)
        try:
            user = self._provision(found, ip)
        except DirectoryRefused as e:  # local_name_conflict, identity_mismatch
            self._login_failed(keys, None, ip, dir_key, source="ldap", reason=e.reason)
        if user["disabled_at"] is not None:
            self._login_failed(keys, user, ip, dir_key, source="ldap", reason="disabled")
        self.clear(dir_key)
        return user

    def _provision(self, found: DirectoryUser, ip: str) -> dict:
        """Create or update the local row of a directory user, bound to the entry's stable
        identity at first sign-in. A role change (groups changed) revokes their sessions and
        tokens like an admin's role change. Refuses (DirectoryRefused) a name taken by a local
        account, or a row bound to another directory entry."""
        with self.conn.transaction():
            old = self.conn.execute(
                "SELECT * FROM users WHERE username = %s FOR UPDATE", (found.username,)
            ).fetchone()
            if old is not None and old["source"] != "ldap":
                raise DirectoryRefused("local_name_conflict")
            if old is not None and old["directory_id"] not in (None, found.identity):
                raise DirectoryRefused("identity_mismatch")
            try:
                with self.conn.transaction():  # savepoint: the identity may be another row's
                    if old is None:
                        row = self.conn.execute(
                            "INSERT INTO users (id, username, display_name, role, source,"
                            " directory_id) VALUES (%s, %s, %s, %s, 'ldap', %s) RETURNING *",
                            (
                                uuid.uuid4(),
                                found.username,
                                found.display_name,
                                found.role,
                                found.identity,
                            ),
                        ).fetchone()
                    else:
                        row = self.conn.execute(
                            "UPDATE users SET display_name = %s, role = %s, directory_id = %s,"
                            " updated_at = now() WHERE id = %s RETURNING *",
                            (found.display_name, found.role, found.identity, old["id"]),
                        ).fetchone()
            except psycopg.errors.UniqueViolation:  # renamed entry, or a racing first sign-in
                raise DirectoryRefused("identity_mismatch") from None
            if old is None:
                self.audit("user_create", "success", "ldap", row["id"], ip, source="ldap")
            elif old["role"] != found.role:
                self.revoke_all(row["id"], "role change")
                n = revoke_user_tokens(self.conn, row["id"])
                self.audit(
                    "role_change",
                    "success",
                    "ldap",
                    row["id"],
                    ip,
                    old=old["role"],
                    new=found.role,
                    tokens_revoked=n,
                    groups=list(found.groups)[:20],
                )
        return row

    def mfa_required(self, user: dict) -> bool:
        """Admins (local or directory) when "require MFA for admins" is on; every directory
        user when the LDAP `require_mfa` setting is on."""
        admin = user["role"] == Role.ADMIN and self.s.require_mfa_admins
        return admin or (user["source"] == "ldap" and self.ldap.require_mfa)

    def _stage_after_password(self, user: dict) -> Stage:
        if self._mfa(user["id"], confirmed=True):
            return "mfa"
        if self.mfa_required(user):
            return "enrol"
        return "full"

    def login_mfa(
        self, p: Principal, code: str | None, recovery: str | None, ip: str, ua: str
    ) -> tuple[str, int | None]:
        """MFA step for a session in stage 'mfa': a TOTP code or a recovery code. Returns the new
        full session value (rotated) and, for a recovery code, how many are left."""
        key = _key("mfa", p.user_id)
        self._refuse_if_locked(key)
        left = None
        if recovery:
            ok = self._use_recovery_code(p.user_id, recovery)
            left = self._codes_left(p.user_id) if ok else None
        else:
            ok = bool(code) and self._totp_ok(p.user_id, code or "", confirmed=True)
        method = "recovery_code" if recovery else "totp"
        if not ok:
            self.fail(key, self.s.lockout_threshold)
            self.audit("mfa_verify", "failure", p.username, p.user_id, ip, method=method)
            raise AuthError(401, "That code didn't work. Try again.")
        self.clear(key)
        self.revoke_session(p.credential_id, "mfa completed")
        raw = self.new_session(p.user_id, "full", ip, ua)
        self.audit("mfa_verify", "success", p.username, p.user_id, ip, method=method)
        return raw, left

    # --- sessions ------------------------------------------------------------------------

    def ttl(self, stage: Stage) -> int:
        return self.s.absolute_timeout_hours * 3600 if stage == "full" else PENDING_SECONDS

    def new_session(self, user_id, stage: Stage, ip: str, ua: str) -> str:
        raw = secrets.token_urlsafe(32)  # 256 bits; only its hash is stored
        ttl = self.ttl(stage)
        row = self.conn.execute("SELECT source FROM users WHERE id = %s", (user_id,)).fetchone()
        if row and row["source"] == "ldap":  # a group removal takes effect within this cap
            ttl = min(ttl, self.ldap.session_max_hours * 3600)
        self.conn.execute(
            "INSERT INTO sessions (id, token_hash, user_id, stage, expires_at, ip, user_agent)"
            " VALUES (%s, %s, %s, %s, now() + make_interval(secs => %s), %s, %s)",
            (uuid.uuid4(), sha256(raw), user_id, stage, ttl, ip[:64], ua[:200]),
        )
        return raw

    def session(self, raw: str, touch: bool = True) -> Principal | None:
        """`touch=False`: a re-check (the event stream) that does not count as activity."""
        if not raw or len(raw) > 128:
            return None
        row = self.conn.execute(
            "SELECT s.id, s.user_id, s.stage, s.revoked_at, u.username, u.role, u.disabled_at,"
            " now() >= s.expires_at AS expired,"
            " now() - s.last_seen_at > make_interval(mins => %s) AS idle,"
            " now() - s.last_seen_at > interval '30 seconds' AS stale"
            " FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token_hash = %s",
            (self.s.idle_timeout_minutes, sha256(raw)),
        ).fetchone()
        if row is None or row["revoked_at"] is not None or row["disabled_at"] is not None:
            return None
        if row["expired"] or row["idle"]:
            self.revoke_session(row["id"], "expired" if row["expired"] else "idle")
            return None
        if row["stale"] and touch:
            self.conn.execute(
                "UPDATE sessions SET last_seen_at = now() WHERE id = %s", (row["id"],)
            )
        return Principal(
            str(row["user_id"]),
            row["username"],
            Role(row["role"]),
            "session",
            row["stage"],
            str(row["id"]),
        )

    def revoke_raw(self, raw: str, reason: str) -> None:
        if raw and len(raw) <= 128:
            self.conn.execute(
                "UPDATE sessions SET revoked_at = now(), revoked_reason = %s"
                " WHERE token_hash = %s AND revoked_at IS NULL",
                (reason, sha256(raw)),
            )

    def revoke_session(self, session_id, reason: str) -> bool:
        cur = self.conn.execute(
            "UPDATE sessions SET revoked_at = now(), revoked_reason = %s"
            " WHERE id = %s AND revoked_at IS NULL",
            (reason, session_id),
        )
        return cur.rowcount == 1

    def revoke_all(self, user_id, reason: str) -> int:
        cur = self.conn.execute(
            "UPDATE sessions SET revoked_at = now(), revoked_reason = %s"
            " WHERE user_id = %s AND revoked_at IS NULL",
            (reason, user_id),
        )
        return cur.rowcount

    def sessions(self, user_id) -> list[dict]:
        return self.conn.execute(
            "SELECT id, stage, created_at, last_seen_at, expires_at, ip, user_agent FROM sessions"
            " WHERE user_id = %s AND revoked_at IS NULL AND expires_at > now()"
            " AND now() - last_seen_at <= make_interval(mins => %s) ORDER BY created_at DESC",
            (user_id, self.s.idle_timeout_minutes),
        ).fetchall()

    def reissue(self, p: Principal, reason: str, ip: str, ua: str) -> str:
        """After a password or MFA change: every session of the user is revoked and the caller
        gets a fresh one (rotation)."""
        self.revoke_all(p.user_id, reason)
        return self.new_session(p.user_id, "full", ip, ua)

    # --- API tokens ----------------------------------------------------------------------

    def token(self, raw: str) -> Principal | None:
        if not TOKEN.fullmatch(raw):
            return None
        row = self.conn.execute(
            "SELECT t.id, t.user_id, t.role, t.revoked_at, u.username, u.role AS user_role,"
            " u.disabled_at, now() >= t.expires_at AS expired,"
            " (t.last_used_at IS NULL OR t.last_used_at < now() - interval '60 seconds') AS stale"
            " FROM api_tokens t JOIN users u ON u.id = t.user_id WHERE t.token_hash = %s",
            (sha256(raw),),
        ).fetchone()
        if row is None or row["revoked_at"] or row["disabled_at"] or row["expired"]:
            return None
        if row["stale"]:
            self.conn.execute(
                "UPDATE api_tokens SET last_used_at = now() WHERE id = %s", (row["id"],)
            )
        # A token never outranks its owner today (a demoted owner demotes the token).
        role = Role.lower(Role(row["role"]), Role(row["user_role"]))
        return Principal(
            str(row["user_id"]), row["username"], role, "token", "full", str(row["id"])
        )

    def create_token(
        self, p: Principal, name: str, role: Role, days: int, ip: str
    ) -> tuple[str, dict]:
        if not p.role.covers(role):
            self.audit("token_create", "refused", p.username, p.user_id, ip, role=role)
            raise AuthError(403, "A token's role can't be higher than your own.")
        if self.user(p.user_id)["source"] != "local":
            # A token would keep a role for up to 90 days with no group check (T12.4).
            self.audit("token_create", "refused", p.username, p.user_id, ip, reason="ldap")
            raise AuthError(403, "API tokens are for local accounts. Ask an admin for one.")
        if not 1 <= days <= TOKEN_MAX_DAYS:
            raise AuthError(422, f"Token expiry must be 1 to {TOKEN_MAX_DAYS} days.")
        raw = "pmxt_" + secrets.token_urlsafe(32)
        row = self.conn.execute(
            "INSERT INTO api_tokens (id, user_id, name, role, token_hash, expires_at)"
            " VALUES (%s, %s, %s, %s, %s, now() + make_interval(days => %s))"
            " RETURNING id, name, role, created_at, expires_at",
            (uuid.uuid4(), p.user_id, name, str(role), sha256(raw), days),
        ).fetchone()
        self.audit(
            "token_create",
            "success",
            p.username,
            p.user_id,
            ip,
            token_id=str(row["id"]),
            name=name,
            role=str(role),
            days=days,
        )
        return raw, row

    def tokens(self, p: Principal) -> list[dict]:
        return self.conn.execute(
            "SELECT t.id, t.name, t.role, u.username AS owner, t.created_at, t.expires_at,"
            " t.last_used_at, t.revoked_at, now() >= t.expires_at AS expired"
            " FROM api_tokens t JOIN users u ON u.id = t.user_id"
            " WHERE %s OR t.user_id = %s ORDER BY t.created_at DESC",
            (p.role == Role.ADMIN, p.user_id),
        ).fetchall()

    def revoke_token(self, p: Principal, token_id: str, ip: str) -> None:
        row = self.conn.execute(
            "SELECT id, user_id FROM api_tokens WHERE id = %s", (token_id,)
        ).fetchone()
        if row is None or (p.role != Role.ADMIN and str(row["user_id"]) != p.user_id):
            raise AuthError(404, "no such token")  # another user's token looks missing
        self.conn.execute(
            "UPDATE api_tokens SET revoked_at = now() WHERE id = %s AND revoked_at IS NULL",
            (token_id,),
        )
        self.audit("token_revoke", "success", p.username, row["user_id"], ip, token_id=token_id)

    # --- users ---------------------------------------------------------------------------

    def user(self, user_id: str) -> dict:
        row = self.conn.execute(
            "SELECT u.*, (m.confirmed_at IS NOT NULL) AS mfa FROM users u"
            " LEFT JOIN user_mfa m ON m.user_id = u.id WHERE u.id = %s",
            (user_id,),
        ).fetchone()
        if row is None:
            raise AuthError(404, "no such user")
        return row

    def users(self) -> list[dict]:
        return self.conn.execute(
            "SELECT u.*, (m.confirmed_at IS NOT NULL) AS mfa FROM users u"
            " LEFT JOIN user_mfa m ON m.user_id = u.id ORDER BY u.username"
        ).fetchall()

    def create_user(
        self,
        actor: Principal | str,
        username: str,
        display_name: str,
        role: Role,
        password: str,
        ip: str = "",
    ) -> dict:
        name = username.strip().lower()
        if not USERNAME.fullmatch(name):
            raise AuthError(422, "User names are 1 to 64 of a-z, 0-9, '.', '_' and '-'.")
        try:
            passwords.check(password, name)
        except passwords.PasswordRefused as e:
            raise AuthError(422, str(e)) from None
        try:
            with self.conn.transaction():
                row = self.conn.execute(
                    "INSERT INTO users (id, username, display_name, role, password_hash,"
                    " password_changed_at) VALUES (%s, %s, %s, %s, %s, now()) RETURNING *",
                    (
                        uuid.uuid4(),
                        name,
                        display_name,
                        str(role),
                        passwords.hash_password(password),
                    ),
                ).fetchone()
        except psycopg.errors.UniqueViolation:
            raise AuthError(409, "That user name is taken.") from None
        who, who_id = (
            (actor.username, actor.user_id) if isinstance(actor, Principal) else (actor, None)
        )
        self.audit("user_create", "success", who, row["id"], ip, actor_id=who_id, role=str(role))
        return row

    def _keeps_an_admin(self, user: dict) -> None:
        """Refuse a change that would leave no active local admin (break-glass access: a
        directory admin cannot sign in while the directory is down)."""
        if (
            user["role"] != Role.ADMIN
            or user["disabled_at"] is not None
            or user["source"] != "local"
        ):
            return
        other = self.conn.execute(
            "SELECT 1 FROM users WHERE role = 'admin' AND disabled_at IS NULL AND source = 'local'"
            " AND id <> %s LIMIT 1",
            (user["id"],),
        ).fetchone()
        if other is None:
            raise AuthError(409, "Keep at least one active admin.")

    def set_role(self, p: Principal, user_id: str, role: Role, ip: str) -> dict:
        with self.conn.transaction():
            self.conn.execute("SELECT pg_advisory_xact_lock(%s)", (ADMIN_LOCK,))
            user = self.user(user_id)
            if user["source"] != "local":
                raise AuthError(409, "A directory user's role comes from their groups.")
            if user["role"] == role:
                return user
            if role != Role.ADMIN:
                self._keeps_an_admin(user)
            self.conn.execute(
                "UPDATE users SET role = %s, updated_at = now() WHERE id = %s", (str(role), user_id)
            )
            self.revoke_all(user_id, "role change")
            n = revoke_user_tokens(self.conn, user_id)
            self.audit(
                "role_change",
                "success",
                p.username,
                user_id,
                ip,
                old=user["role"],
                new=str(role),
                tokens_revoked=n,
            )
        return self.user(user_id)

    def set_disabled(self, p: Principal, user_id: str, disabled: bool, ip: str) -> dict:
        with self.conn.transaction():
            self.conn.execute("SELECT pg_advisory_xact_lock(%s)", (ADMIN_LOCK,))
            user = self.user(user_id)
            if disabled:
                self._keeps_an_admin(user)
            self.conn.execute(
                "UPDATE users SET disabled_at = CASE WHEN %s THEN coalesce(disabled_at, now())"
                " END, updated_at = now() WHERE id = %s",
                (disabled, user_id),
            )
            n = 0
            if disabled:
                self.revoke_all(user_id, "disabled")
                n = revoke_user_tokens(self.conn, user_id)
            self.audit(
                "user_disable" if disabled else "user_enable",
                "success",
                p.username,
                user_id,
                ip,
                tokens_revoked=n,
            )
        return self.user(user_id)

    def _check_password(self, p: Principal, password: str, ip: str) -> dict:
        """Re-authentication for account security changes (throttled like login)."""
        key = _key("user", p.username)
        self._refuse_if_locked(key)
        user = self.user(p.user_id)
        if not self._password_ok(user, password):
            self.fail(key, self.s.lockout_threshold)
            self.audit("reauth", "failure", p.username, p.user_id, ip)
            raise AuthError(403, "That password is not correct.")
        return user

    def _password_ok(self, user: dict, password: str) -> bool:
        if user["source"] == "local":
            return passwords.verify(user["password_hash"], password)
        passwords.verify(None, password)
        if not self.ldap.enabled:
            return False
        try:
            with self.directory() as d:
                return d.authenticate(user["username"], password).username == user["username"]
        except DirectoryRefused:
            return False
        except DirectoryUnavailable:
            raise AuthError(503, "The directory is unavailable. Try again later.") from None

    def change_password(self, p: Principal, current: str, new: str, ip: str) -> None:
        if self.user(p.user_id)["source"] != "local":
            raise AuthError(409, "Change your password in your organisation's directory.")
        self._check_password(p, current, ip)
        try:
            passwords.check(new, p.username)
        except passwords.PasswordRefused as e:
            raise AuthError(422, str(e)) from None
        with self.conn.transaction():
            self.conn.execute(
                "UPDATE users SET password_hash = %s, password_changed_at = now(),"
                " updated_at = now() WHERE id = %s",
                (passwords.hash_password(new), p.user_id),
            )
            n = revoke_user_tokens(self.conn, p.user_id)
            self.audit("password_change", "success", p.username, p.user_id, ip, tokens_revoked=n)

    # --- MFA (TOTP, RFC 6238) -----------------------------------------------------------

    def _vault(self) -> Vault:
        try:
            if self._kek is None:
                raise VaultError("no KEK")
            return Vault(self.conn, self._kek())
        except VaultError:
            raise AuthError(503, "MFA is unavailable: the engine cannot open the vault.") from None

    def _mfa(self, user_id, confirmed: bool) -> dict | None:
        row = self.conn.execute("SELECT * FROM user_mfa WHERE user_id = %s", (user_id,)).fetchone()
        if row is None or (row["confirmed_at"] is not None) != confirmed:
            return None
        return row

    def _totp_ok(self, user_id, code: str, confirmed: bool) -> bool:
        """±1 time step; a step at or before the last accepted one is a replay and refused."""
        row = self._mfa(user_id, confirmed)
        if row is None or not re.fullmatch(r"\d{6}", code):
            return False
        now, matched = time.time(), 0
        with self._vault().use(str(row["secret_id"]), PLATFORM) as p:
            totp = pyotp.TOTP(p.text())
            for offset in (-1, 0, 1):
                at = now + offset * totp.interval
                if hmac.compare_digest(totp.at(at), code):
                    matched = int(at // totp.interval)
        if not matched:
            return False
        cur = self.conn.execute(
            "UPDATE user_mfa SET last_step = %s WHERE user_id = %s AND last_step < %s",
            (matched, user_id, matched),
        )
        return cur.rowcount == 1

    def mfa_enrol(self, p: Principal, ip: str, password: str | None = None) -> dict:
        """A signed-in user re-authenticates; a user still in the "enrol" stage has just
        entered the password at sign-in."""
        if p.stage == "full":
            if not password:
                raise AuthError(422, "Enter your current password to set up MFA.")
            self._check_password(p, password, ip)
        if self._mfa(p.user_id, confirmed=True):
            raise AuthError(409, "MFA is already on. Turn it off first to enrol a new device.")
        secret = pyotp.random_base32()
        secret_id = self._vault().put(PLATFORM, f"auth.totp.{p.user_id}", secret, p.username)
        self.conn.execute(
            "INSERT INTO user_mfa (user_id, secret_id) VALUES (%s, %s) ON CONFLICT (user_id)"
            " DO UPDATE SET secret_id = EXCLUDED.secret_id, last_step = 0"
            " WHERE user_mfa.confirmed_at IS NULL",
            (p.user_id, secret_id),
        )
        self.audit("mfa_enrol", "success", p.username, p.user_id, ip)
        uri = pyotp.TOTP(secret).provisioning_uri(name=p.username, issuer_name=TOTP_ISSUER)
        return {"secret": secret, "otpauth_uri": uri}  # shown to its owner once, to scan

    def mfa_confirm(self, p: Principal, code: str, ip: str) -> list[str]:
        key = _key("mfa", p.user_id)
        self._refuse_if_locked(key)
        if not self._totp_ok(p.user_id, code, confirmed=False):
            self.fail(key, self.s.lockout_threshold)
            self.audit("mfa_confirm", "failure", p.username, p.user_id, ip)
            raise AuthError(
                400, "That code didn't match. Check the time on your device and try again."
            )
        self.clear(key)
        self.conn.execute(
            "UPDATE user_mfa SET confirmed_at = now() WHERE user_id = %s", (p.user_id,)
        )
        codes = self._new_recovery_codes(p.user_id)
        self.audit("mfa_confirm", "success", p.username, p.user_id, ip)
        return codes

    def mfa_disable(self, p: Principal, password: str, ip: str) -> None:
        user = self._check_password(p, password, ip)
        if self.mfa_required(user):
            who = "admins" if user["role"] == Role.ADMIN else "directory users"
            raise AuthError(409, f"MFA is required for {who}.")
        row = self.conn.execute(
            "DELETE FROM user_mfa WHERE user_id = %s RETURNING secret_id", (p.user_id,)
        ).fetchone()
        self.conn.execute("DELETE FROM recovery_codes WHERE user_id = %s", (p.user_id,))
        if row:  # the vault keeps no deletes: overwrite the old secret with noise
            self._vault().put(PLATFORM, f"auth.totp.{p.user_id}", secrets.token_hex(32), p.username)
        self.audit("mfa_disable", "success", p.username, p.user_id, ip)

    def regenerate_codes(self, p: Principal, password: str, ip: str) -> list[str]:
        self._check_password(p, password, ip)
        if not self._mfa(p.user_id, confirmed=True):
            raise AuthError(409, "Turn on MFA first.")
        codes = self._new_recovery_codes(p.user_id)
        self.audit("recovery_codes", "success", p.username, p.user_id, ip)
        return codes

    def _new_recovery_codes(self, user_id) -> list[str]:
        """Ten single-use codes of 80 random bits, stored as SHA-256 (they are not guessable,
        so a fast hash is enough, as for tokens). Replaces any earlier codes."""
        codes = [
            "-".join("".join(secrets.choice(RECOVERY_ALPHABET) for _ in range(4)) for _ in range(4))
            for _ in range(RECOVERY_CODES)
        ]
        with self.conn.transaction():
            self.conn.execute("DELETE FROM recovery_codes WHERE user_id = %s", (user_id,))
            for c in codes:
                self.conn.execute(
                    "INSERT INTO recovery_codes (user_id, code_hash) VALUES (%s, %s)",
                    (user_id, self._code_hash(user_id, c)),
                )
        return codes

    @staticmethod
    def _code_hash(user_id, code: str) -> str:
        return sha256(f"{user_id}:{re.sub(r'[^a-z0-9]', '', code.lower())}")

    def _use_recovery_code(self, user_id, code: str) -> bool:
        if not self._mfa(user_id, confirmed=True):
            return False
        cur = self.conn.execute(
            "UPDATE recovery_codes SET used_at = now()"
            " WHERE user_id = %s AND code_hash = %s AND used_at IS NULL",
            (user_id, self._code_hash(user_id, code[:64])),
        )
        return cur.rowcount == 1

    def _codes_left(self, user_id) -> int:
        return self.conn.execute(
            "SELECT count(*) AS n FROM recovery_codes WHERE user_id = %s AND used_at IS NULL",
            (user_id,),
        ).fetchone()["n"]

    # --- first run and break-glass -------------------------------------------------------

    def setup(
        self, token: str, username: str, display_name: str, password: str, ip: str, ua: str
    ) -> tuple[str, dict, Stage]:
        """Create the first admin with the one-time setup token (single use, 60 minutes)."""
        if admin_exists(self.conn):
            raise AuthError(409, "Setup is already complete. Sign in instead.")
        try:
            passwords.check(password, username.strip().lower())
        except passwords.PasswordRefused as e:  # checked first: a refused password keeps the token
            raise AuthError(422, str(e)) from None
        user = None
        with self.conn.transaction():
            self.conn.execute("SELECT pg_advisory_xact_lock(%s)", (ADMIN_LOCK,))
            row = self.conn.execute(
                "SELECT token_hash, used_at, expires_at > now() AS valid FROM setup_token"
                " FOR UPDATE"
            ).fetchone()
            done = admin_exists(self.conn)
            ok = (
                not done
                and row is not None
                and row["used_at"] is None
                and row["valid"]
                and hmac.compare_digest(row["token_hash"], sha256(token))
            )
            if ok:
                user = self.create_user("setup", username, display_name, Role.ADMIN, password, ip)
                self.conn.execute("UPDATE setup_token SET used_at = now()")
        if user is None:
            self.audit("setup", "failure", "anonymous", ip=ip)
            if done:
                raise AuthError(409, "Setup is already complete. Sign in instead.")
            raise AuthError(403, SETUP_INVALID)
        self.audit("setup", "success", user["username"], user["id"], ip)
        stage = self._stage_after_password(user)
        return self.new_session(user["id"], stage, ip, ua), user, stage


def admin_reset(conn: psycopg.Connection, username: str, password: str) -> dict:
    """Break-glass (host CLI, database owner): a new password, MFA cleared, the account enabled
    and unlocked, every session and API token revoked. The user enrols MFA again at the next
    sign-in."""
    name = username.strip().lower()
    try:
        passwords.check(password, name)
    except passwords.PasswordRefused as e:
        raise AuthError(422, str(e)) from None
    with conn.transaction():
        user = conn.execute(
            "UPDATE users SET password_hash = %s, password_changed_at = now(), disabled_at = NULL,"
            " updated_at = now() WHERE username = %s AND source = 'local' RETURNING *",
            (passwords.hash_password(password), name),
        ).fetchone()
        if user is None:
            raise AuthError(404, f"no local user {name}")
        conn.execute("DELETE FROM recovery_codes WHERE user_id = %s", (user["id"],))
        conn.execute("DELETE FROM user_mfa WHERE user_id = %s", (user["id"],))
        conn.execute(
            "DELETE FROM auth_throttle WHERE key = ANY(%s)",
            ([_key("user", name), _key("mfa", str(user["id"]))],),
        )
        conn.execute(
            "UPDATE sessions SET revoked_at = now(), revoked_reason = 'admin reset'"
            " WHERE user_id = %s AND revoked_at IS NULL",
            (user["id"],),
        )
        n = revoke_user_tokens(conn, user["id"])
        events.record(
            conn, "admin_reset", "success", "cli:admin-reset", str(user["id"]), tokens_revoked=n
        )
    return user


def revoke_directory_sessions(conn: psycopg.Connection, reason: str) -> int:
    """Every session of every directory user (LDAP turned off, servers or CA changed)."""
    cur = conn.execute(
        "UPDATE sessions SET revoked_at = now(), revoked_reason = %s WHERE revoked_at IS NULL"
        " AND user_id IN (SELECT id FROM users WHERE source = 'ldap')",
        (reason,),
    )
    return cur.rowcount


def revoke_user_tokens(conn: psycopg.Connection, user_id) -> int:
    """Every API token of the user (password or role change, disable, admin reset)."""
    cur = conn.execute(
        "UPDATE api_tokens SET revoked_at = now() WHERE user_id = %s AND revoked_at IS NULL",
        (user_id,),
    )
    return cur.rowcount
