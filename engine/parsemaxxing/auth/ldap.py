"""Directory sign-in with `ldap3` (design 7.4, threats T12.1 to T12.7).

LDAPS or StartTLS only (plain LDAP refused at config and here at connect); the certificate is
checked against the uploaded CA bundle only, host name included, by the standard library's TLS
(ldap3's own host name check is bypassed, see `_VerifiedTls`). Servers are tried in order.

Login: refuse an empty password before any connection -> service bind -> search with the user
name escaped per RFC 4515 -> exactly one entry -> bind as that entry's DN -> read groups -> the
highest mapped role; no mapped group means no access.

Hygiene: a `Directory` holds the bind password only while the caller's vault block is open and
its repr is redacted; ldap3 objects (whose repr shows the password) are never logged, raised or
returned. Failures carry a short reason code for the audit log, never a password or a server
message; the user only ever sees the one generic sign-in failure.
"""

import logging
import re
import ssl
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime

import ldap3
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from ldap3.core import exceptions as lx
from ldap3.protocol.sasl.sasl import validate_simple_password
from ldap3.utils.conv import escape_filter_chars
from ldap3.utils.dn import safe_dn

from parsemaxxing.settings.groups import LdapServer, LdapSettings

log = logging.getLogger(__name__)
IN_CHAIN = "1.2.840.113556.1.4.1941"  # LDAP_MATCHING_RULE_IN_CHAIN (AD nested groups)
MAX_GROUPS = 1000  # groups read per user, all modes
MAX_DEPTH = 8  # nesting levels followed in `member` mode with nested_groups
NAME = re.compile(r"[a-z0-9][a-z0-9._@-]{0,127}")  # a directory user's local name
_PEM_BLOCK = re.compile(r"-----BEGIN ([A-Z0-9 ]+)-----")
CA_MAX_BYTES = 256 * 1024


class DirectoryRefused(Exception):
    """This user cannot sign in. `reason` is an audit code: never shown to the user.
    `identity` is the entry's stable identity when the search found exactly one entry (its
    lockout key), else empty."""

    def __init__(self, reason: str, identity: str = ""):
        super().__init__(reason)
        self.reason, self.identity = reason, identity


class DirectoryUnavailable(Exception):
    """No server could answer (network, TLS, service bind). `reason` is an audit code."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class DirectoryUser:
    dn: str
    username: str
    display_name: str
    groups: tuple[str, ...]  # the user's groups that are in the mapping
    role: str
    identity: str  # entryUUID / objectGUID, else the DN: stable across renames of the name


def identity_of(entry: dict) -> str:
    """The entry's stable identity: OpenLDAP entryUUID, AD objectGUID, else the normalised DN."""
    attrs, raw = entry.get("attributes", {}), entry.get("raw_attributes", {})
    if value := _values(attrs.get("entryUUID")):
        return f"entryUUID:{value[0].strip().lower()}"
    guid = raw.get("objectGUID")
    guid = guid[0] if isinstance(guid, list) and guid else guid
    if isinstance(guid, bytes) and len(guid) == 16:
        return f"objectGUID:{uuid.UUID(bytes_le=guid)}"
    return f"dn:{norm_dn(entry['dn'])}"


def check_password_text(password: str) -> None:
    """Before any connection: empty (unauthenticated bind, T12.3) or not valid under SASLprep
    (RFC 4013: control and prohibited characters) is refused."""
    if not password:
        raise DirectoryRefused("empty_password")
    if re.search(r"[\x00-\x1f\x7f]", password):
        raise DirectoryRefused("bad_password")
    try:
        if not validate_simple_password(password):
            raise DirectoryRefused("empty_password")
    except lx.LDAPException:
        raise DirectoryRefused("bad_password") from None


# --- CA bundle -------------------------------------------------------------------------------


def check_ca_bundle(pem: str) -> list[dict]:
    """Validate an uploaded CA bundle: PEM certificates only (a private key or anything else is
    refused), each a CA, none expired. Returns what may be shown about each one."""
    if len(pem.encode("utf-8")) > CA_MAX_BYTES:
        raise ValueError("The CA bundle is larger than 256 KB.")
    kinds = set(_PEM_BLOCK.findall(pem))
    if not kinds:
        raise ValueError("The CA bundle holds no PEM certificate.")
    if kinds != {"CERTIFICATE"}:
        raise ValueError("The CA bundle may hold only certificates (BEGIN CERTIFICATE blocks).")
    try:
        certs = x509.load_pem_x509_certificates(pem.encode("utf-8"))
    except ValueError:
        raise ValueError("The CA bundle is not valid PEM.") from None
    if len(certs) != pem.count("-----BEGIN CERTIFICATE-----"):
        raise ValueError("The CA bundle is not valid PEM.")
    now = datetime.now(UTC)
    for cert in certs:
        try:
            ca = cert.extensions.get_extension_for_class(x509.BasicConstraints).value.ca
        except x509.ExtensionNotFound:
            ca = False
        if not ca:
            raise ValueError(f"{cert.subject.rfc4514_string()[:200]} is not a CA certificate.")
        if cert.not_valid_after_utc < now:
            raise ValueError(f"{cert.subject.rfc4514_string()[:200]} has expired.")
    try:  # the standard library must accept it too
        ssl.create_default_context(cadata=pem)
    except ssl.SSLError:
        raise ValueError("The CA bundle is not usable for TLS.") from None
    return [cert_summary(c) for c in certs]


def ca_summary(pem: str) -> list[dict]:
    """What may be shown about a stored bundle (no validity rules: an expired CA shows)."""
    return [cert_summary(c) for c in x509.load_pem_x509_certificates(pem.encode("utf-8"))]


def cert_summary(cert: x509.Certificate) -> dict:
    return {
        "subject": cert.subject.rfc4514_string()[:300],
        "issuer": cert.issuer.rfc4514_string()[:300],
        "not_after": cert.not_valid_after_utc.isoformat(),
        "sha256": cert.fingerprint(hashes.SHA256()).hex(),
    }


def tls_context(ca_pem: str) -> ssl.SSLContext:
    """Trust only the uploaded bundle (never the system store); host name always checked."""
    ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cadata=ca_pem)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.check_hostname = True
    ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx


class _VerifiedTls(ldap3.Tls):
    """ldap3's Tls turns the standard library's host name check off and does its own; this
    wraps with our context instead, so OpenSSL checks the chain and the host name (IP SANs
    included) during the handshake. The last TLS error is kept for the connection test."""

    def __init__(self, context: ssl.SSLContext, hostname: str):
        super().__init__(validate=ssl.CERT_REQUIRED)
        self._context, self._hostname = context, hostname
        self.error: Exception | None = None

    def wrap_socket(self, connection, do_handshake=False):  # always handshakes
        try:
            connection.socket = self._context.wrap_socket(
                connection.socket, server_side=False, server_hostname=self._hostname
            )
        except (ssl.SSLError, OSError) as e:
            self.error = e
            raise


def _describe(e: BaseException, tls: _VerifiedTls | None) -> tuple[str, str]:
    """(step, message) for a connection failure: safe to show to an admin (no server text)."""
    if tls is not None and isinstance(tls.error, ssl.SSLCertVerificationError):
        return "certificate", f"certificate refused: {str(tls.error.verify_message)[:200]}"
    if tls is not None and tls.error is not None:
        return "tls", "TLS handshake failed (protocol or cipher mismatch, or not a TLS port)"
    if isinstance(e, lx.LDAPStartTLSError):
        return "tls", "the server refused StartTLS"
    if isinstance(e, lx.LDAPSocketOpenError):
        return "connect", "could not connect (refused, unreachable or timed out)"
    if isinstance(e, lx.LDAPSocketReceiveError | TimeoutError):
        return "connect", "no answer before the read timeout"
    return "connect", "directory error"


# --- the client ------------------------------------------------------------------------------

Connect = Callable[[LdapServer, str, str], tuple[ldap3.Connection, "_VerifiedTls | None"]]


@dataclass
class Directory:
    """One use of the directory: build it inside the vault blocks that hold the bind password
    and the CA bundle, use it, drop it. `connect` is replaced in tests (ldap3 MOCK_SYNC)."""

    s: LdapSettings
    _bind_password: str = field(repr=False)
    _ca_pem: str = field(repr=False)
    connect: Connect | None = field(default=None, repr=False)
    _first: int = field(default=0, repr=False)  # the server that answered last
    _tls: "_VerifiedTls | None" = field(default=None, repr=False)  # of the last connection

    def __repr__(self) -> str:
        return f"Directory(servers={len(self.s.servers)}, <credentials redacted>)"

    # --- connections ---------------------------------------------------------------------

    def _open(self, server: LdapServer, user: str, password: str):
        if not server.ldaps and not server.start_tls:  # config refuses it too
            raise DirectoryUnavailable("plain_ldap_refused")
        if self.connect is not None:
            return self.connect(server, user, password)
        tls = self._tls = _VerifiedTls(tls_context(self._ca_pem), server.host)
        srv = ldap3.Server(
            server.host,
            port=server.port,
            use_ssl=server.ldaps,
            tls=tls,
            get_info=ldap3.NONE,
            connect_timeout=self.s.connect_timeout_seconds,
        )
        conn = ldap3.Connection(
            srv,
            user=user,
            password=password,
            authentication=ldap3.SIMPLE,
            receive_timeout=self.s.read_timeout_seconds,
            raise_exceptions=False,
            read_only=True,
            auto_referrals=False,
        )
        try:
            conn.open()
            if server.start_tls and not conn.start_tls():
                raise lx.LDAPStartTLSError("StartTLS failed")
        except BaseException:
            _close(conn)
            raise
        if not (srv.ssl or conn.tls_started):  # never send a bind in clear
            _close(conn)
            raise DirectoryUnavailable("plain_ldap_refused")
        return conn, tls

    def _bound(self, user: str, password: str, service: bool) -> ldap3.Connection:
        """A connection bound as `user`, trying servers in order from the last one that worked.
        Only transport failures (network, TLS) move to the next server; any bind result is an
        answer (a retry would count twice in the directory's own lockout)."""
        check_password_text(password)  # an empty password would be an unauthenticated bind
        if not self.s.servers:
            raise DirectoryUnavailable("no_servers")
        n, failures = len(self.s.servers), []
        for i in [(self._first + k) % n for k in range(n)]:
            server = self.s.servers[i]
            try:
                conn, _ = self._open(server, user, password)
            except DirectoryUnavailable:
                raise
            except (lx.LDAPException, OSError, ssl.SSLError) as e:
                failures.append(f"{i}:{type(e).__name__}")
                continue
            try:
                ok = conn.bind()
            except (lx.LDAPException, OSError) as e:
                failures.append(f"{i}:{type(e).__name__}")
                _close(conn)
                continue
            if ok:
                self._first = i
                return conn
            # Any bind result is an answer, never a reason to try the next server with the
            # same password (invalidCredentials, unwillingToPerform, constraintViolation...).
            result = str((conn.result or {}).get("description", ""))[:40] or "bind_failed"
            _close(conn)
            if service:
                raise DirectoryUnavailable(f"service_bind_refused:{result}")
            raise DirectoryRefused(
                "bad_password" if result == "invalidCredentials" else f"bind_refused:{result}"
            )
        log.warning("directory: no server answered (%s)", ", ".join(failures))
        raise DirectoryUnavailable("unreachable")

    @contextmanager
    def _service(self) -> Iterator[ldap3.Connection]:
        if not self.s.bind_dn:
            raise DirectoryUnavailable("not_configured")
        try:
            conn = self._bound(self.s.bind_dn, self._bind_password, service=True)
        except DirectoryRefused:  # the stored service password itself is empty or invalid
            raise DirectoryUnavailable("service_bind_refused:password") from None
        try:
            yield conn
        finally:
            _close(conn)

    # --- search --------------------------------------------------------------------------

    def _find(self, conn: ldap3.Connection, username: str) -> list[dict]:
        """Entries matching the filter, at most 2 (2 already fails the exactly-one rule). A
        server that stops at its size limit counts as 2 (it found more than it returned)."""
        if not self.s.user_search_base:
            raise DirectoryUnavailable("not_configured")
        flt = self.s.user_filter.replace("{username}", escape_filter_chars(username))
        attrs = [self.s.username_attribute, self.s.display_name_attribute, "entryUUID"]
        attrs.append("objectGUID")
        if self.s.group_mode == "member_of":
            attrs.append("memberOf")
        try:
            conn.search(
                self.s.user_search_base,
                flt,
                ldap3.SUBTREE,
                attributes=attrs,
                size_limit=2,
                time_limit=self.s.read_timeout_seconds,
            )
        except (lx.LDAPException, OSError) as e:
            raise DirectoryUnavailable(f"search_failed:{type(e).__name__}") from None
        result = str((conn.result or {}).get("description", ""))
        if result not in ("success", "sizeLimitExceeded", "noSuchObject"):
            raise DirectoryUnavailable(f"search_failed:{result[:40]}")
        entries = [r for r in conn.response or [] if r.get("type") == "searchResEntry"][:2]
        if result == "sizeLimitExceeded" and len(entries) < 2:
            entries += [{"dn": "", "attributes": {}}] * (2 - len(entries))  # "more than one"
        return entries

    def _paged(self, conn: ldap3.Connection, flt: str) -> list[str]:
        """DNs of groups under the group base matching `flt` (paged)."""
        if not self.s.group_search_base:
            raise DirectoryUnavailable("not_configured")
        out = []
        try:
            for r in conn.extend.standard.paged_search(
                self.s.group_search_base,
                flt,
                ldap3.SUBTREE,
                attributes=["objectClass"],
                paged_size=self.s.page_size,
                time_limit=self.s.read_timeout_seconds,
                generator=True,
            ):
                if r.get("type") == "searchResEntry":
                    out.append(r["dn"])
                    if len(out) >= MAX_GROUPS:
                        break
        except (lx.LDAPException, OSError) as e:
            raise DirectoryUnavailable(f"group_search_failed:{type(e).__name__}") from None
        return out

    def _groups(self, conn: ldap3.Connection, entry: dict) -> list[str]:
        mode, dn = self.s.group_mode, entry["dn"]
        if mode == "member_of":
            return _values(entry.get("attributes", {}).get("memberOf"))[:MAX_GROUPS]
        if mode == "ad_nested":
            return self._paged(conn, f"(member:{IN_CHAIN}:={escape_filter_chars(dn)})")
        found: dict[str, str] = {}
        frontier = [dn]
        for _ in range(MAX_DEPTH if self.s.nested_groups else 1):
            nxt = []
            for member in frontier:
                for g in self._paged(conn, f"(member={escape_filter_chars(member)})"):
                    if norm_dn(g) not in found and len(found) < MAX_GROUPS:
                        found[norm_dn(g)] = g
                        nxt.append(g)
            if not nxt:
                break
            frontier = nxt
        return list(found.values())

    def _map(self, groups: list[str]) -> tuple[tuple[str, ...], str | None]:
        mapping = {norm_dn(k): v for k, v in self.s.group_roles.items()}
        matched = tuple(g for g in groups if norm_dn(g) in mapping)
        roles = {mapping[norm_dn(g)] for g in matched}
        return matched, "admin" if "admin" in roles else "viewer" if roles else None

    # --- the two uses --------------------------------------------------------------------

    def authenticate(
        self, username: str, password: str, before_bind: Callable[[str], None] | None = None
    ) -> DirectoryUser:
        """The login flow. Raises DirectoryRefused (this user may not sign in) or
        DirectoryUnavailable (the directory could not answer). `before_bind(identity)` runs
        after the search and before the user bind (the caller's lockout per identity)."""
        check_password_text(password)  # before any connection or bind (T12.3)
        if not username or len(username) > 256 or re.search(r"[\x00-\x1f\x7f]", username):
            raise DirectoryRefused("bad_username")
        with self._service() as svc:
            entries = self._find(svc, username)
            if len(entries) != 1:  # 0 or more than 1: never pick one (T12.2)
                raise DirectoryRefused("not_found" if not entries else "ambiguous")
            entry = entries[0]
            identity = identity_of(entry)
            attrs = entry.get("attributes", {})
            name = (_values(attrs.get(self.s.username_attribute)) or [""])[0].strip().lower()
            display = (_values(attrs.get(self.s.display_name_attribute)) or [""])[0][:128]
            if before_bind is not None:
                before_bind(identity)
            try:
                _close(self._bound(entry["dn"], password, service=False))
            except DirectoryRefused as e:
                raise DirectoryRefused(e.reason, identity) from None
            matched, role = self._map(self._groups(svc, entry))
        if not NAME.fullmatch(name):
            raise DirectoryRefused("unusable_name", identity)
        if role is None:
            raise DirectoryRefused("no_group", identity)
        return DirectoryUser(entry["dn"], name, display, matched, role, identity)

    def lookup(self, username: str) -> dict:
        """'Test a user lookup' (admin): the found count, and for exactly one entry its DN, its
        mapped groups and the role. No other attribute and no password (T12.7)."""
        with self._service() as svc:
            entries = self._find(svc, username)
            out: dict = {"found": len(entries), "dn": None, "matched_groups": [], "role": None}
            if len(entries) == 1:  # a server size-limit stop counts as 2 (see _find)
                matched, role = self._map(self._groups(svc, entries[0]))
                out |= {"dn": entries[0]["dn"], "matched_groups": list(matched), "role": role}
        out["message"] = (
            "No entry matched the filter."
            if not entries
            else "The filter matched 2 or more entries. Make it match exactly one."
            if len(entries) > 1
            else "Found, but no group maps to a role: this user can't sign in."
            if out["role"] is None
            else f"Found. This user signs in as {out['role']}."
        )
        return out

    def test_connection(self) -> list[dict]:
        """'Test connection' (admin): for each server in order, the connect, TLS and
        certificate, and service bind steps with pass or fail. No secret, no server text."""
        report = []
        for server in self.s.servers:
            steps: list[dict] = []
            self._tls = None
            try:
                conn, _ = self._open(server, self.s.bind_dn or "", self._bind_password)
            except DirectoryUnavailable as e:
                steps.append({"step": "connect", "ok": False, "detail": e.reason})
                report.append({"url": server.url, "ok": False, "steps": steps})
                continue
            except (lx.LDAPException, OSError, ssl.SSLError) as e:
                step, detail = _describe(e, self._tls)
                if step != "connect":
                    steps.append({"step": "connect", "ok": True, "detail": "TCP connected"})
                steps.append({"step": step, "ok": False, "detail": detail})
                report.append({"url": server.url, "ok": False, "steps": steps})
                continue
            steps.append({"step": "connect", "ok": True, "detail": "TCP connected"})
            steps.append({"step": "tls", "ok": True, "detail": _tls_detail(conn, server)})
            peer = _peer_cert(conn)
            steps.append({"step": "certificate", "ok": True, "detail": "trusted", **peer})
            try:
                ok = bool(self._bind_password) and conn.bind()
            except (lx.LDAPException, OSError):
                ok = False
            steps.append(
                {
                    "step": "bind",
                    "ok": ok,
                    "detail": "service bind succeeded"
                    if ok
                    else "service bind refused: check the bind DN and password",
                }
            )
            _close(conn)
            report.append({"url": server.url, "ok": ok, "steps": steps})
        return report


def _tls_detail(conn: ldap3.Connection, server: LdapServer) -> str:
    sock = conn.socket
    version = sock.version() if isinstance(sock, ssl.SSLSocket) else "TLS"
    return f"{'LDAPS' if server.ldaps else 'StartTLS'}, {version}"


def _peer_cert(conn: ldap3.Connection) -> dict:
    sock = conn.socket
    if not isinstance(sock, ssl.SSLSocket):
        return {}
    der = sock.getpeercert(binary_form=True)
    return {"certificate_info": cert_summary(x509.load_der_x509_certificate(der))} if der else {}


def _close(conn: ldap3.Connection) -> None:
    try:
        conn.unbind()
    except (lx.LDAPException, OSError):
        pass


def _values(v) -> list[str]:
    if v is None:
        return []
    if isinstance(v, list | tuple):
        return [str(x) for x in v]
    return [str(v)]


def norm_dn(dn: str) -> str:
    try:
        return safe_dn(dn).lower()
    except lx.LDAPInvalidDnError:
        return dn.strip().lower()
