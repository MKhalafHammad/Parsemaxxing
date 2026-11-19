"""Phase 14 LDAP against a real OpenLDAP server (design 7.4, T12; baseline LDAP-1 to LDAP-6).

Marker `ldap_integration`. The fixture builds `openldap/Dockerfile` (Debian slapd, base pinned
by digest), generates a test CA and a server certificate for `localhost` with `cryptography`,
starts the container with LDAPS (636) and StartTLS (389) published on 127.0.0.1, and seeds
synthetic acme.example users and groups. Without a usable docker the tests skip, unless
PARSEMAXXING_LDAP_IT=1 (CI), where a missing docker is a failure.

Covered: LDAPS and StartTLS work and plain LDAP is refused, a wrong CA and a host name mismatch
are refused, an empty password never reaches a bind, filter injection is refused, exactly one
entry, nested groups (member mode recursion; memberOf through the overlay), no-group users,
failover to the second server, and a group change taking effect at the next sign-in.
AD's LDAP_MATCHING_RULE_IN_CHAIN is not in OpenLDAP: it is covered by the mock tests only.
"""

import dataclasses
import datetime as dt
import os
import shutil
import socket
import ssl
import subprocess
import time
import uuid
from pathlib import Path

import ldap3
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from parsemaxxing.auth.ldap import Directory, DirectoryRefused, DirectoryUnavailable, tls_context
from parsemaxxing.settings import LdapSettings

pytestmark = pytest.mark.ldap_integration

IMAGE = "pmx-test-openldap:bookworm-1"
DOCKERFILE_DIR = Path(__file__).with_name("openldap")
BASE = "dc=acme,dc=example"
ROOT_DN = f"cn=admin,{BASE}"
SVC_DN = f"cn=pmx-svc,ou=services,{BASE}"
# Synthetic credentials of a throwaway test container.
ROOT_PW = "root-synthetic-7c1d"  # gitleaks:allow
SVC_PW = "svc-synthetic-pass-31aa"  # gitleaks:allow
USER_PW = "user-synthetic-pass-82be"  # gitleaks:allow
ADMINS = f"cn=pmx-admins,ou=groups,{BASE}"
VIEWERS = f"cn=pmx-viewers,ou=groups,{BASE}"
OPS = f"cn=ops-team,ou=groups,{BASE}"


def _required() -> bool:
    return os.environ.get("PARSEMAXXING_LDAP_IT") == "1"


def _skip(reason: str):
    if _required():
        pytest.fail(f"LDAP integration required but {reason}")
    pytest.skip(reason)


def _docker(*args: str, timeout: int = 60, check: bool = True) -> subprocess.CompletedProcess:
    cmd = ["docker", *args]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=check)  # noqa: S603


# --- certificates ---------------------------------------------------------------------------


def _name(cn: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])


def make_ca(cn: str):
    key = ec.generate_private_key(ec.SECP256R1())
    now = dt.datetime.now(dt.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(_name(cn))
        .issuer_name(_name(cn))
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=2))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(False, False, False, False, False, True, True, False, False),
            critical=True,
        )
        .sign(key, hashes.SHA256())
    )
    return key, cert


def make_server_cert(ca_key, ca_cert, names: list[str]):
    key = ec.generate_private_key(ec.SECP256R1())
    now = dt.datetime.now(dt.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(_name(names[0]))
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(n) for n in names]), False)
        .add_extension(x509.ExtendedKeyUsage([x509.ExtendedKeyUsageOID.SERVER_AUTH]), False)
        .sign(ca_key, hashes.SHA256())
    )
    return key, cert


def pem(cert) -> str:
    return cert.public_bytes(serialization.Encoding.PEM).decode()


SLAPD_CONF = f"""\
include /etc/ldap/schema/core.schema
include /etc/ldap/schema/cosine.schema
include /etc/ldap/schema/inetorgperson.schema
include /etc/ldap/schema/nis.schema
modulepath /usr/lib/ldap
moduleload back_mdb
moduleload memberof
pidfile /tmp/slapd.pid
TLSCACertificateFile /cfg/ca.pem
TLSCertificateFile /cfg/server.pem
TLSCertificateKeyFile /cfg/server.key
TLSProtocolMin 3.3
database mdb
maxsize 10485760
suffix "{BASE}"
rootdn "{ROOT_DN}"
rootpw {ROOT_PW}
directory /tmp/pmxdb
overlay memberof
memberof-group-oc groupOfNames
memberof-member-ad member
memberof-memberof-ad memberOf
memberof-refint TRUE
access to attrs=userPassword by self auth by anonymous auth by * none
access to * by dn.exact="{SVC_DN}" read by self read by * none
"""


@dataclasses.dataclass
class Ldap:
    ldaps_port: int
    plain_port: int
    ca_pem: str

    def server(self, **kw) -> dict:
        return {"url": f"ldaps://localhost:{self.ldaps_port}"} | kw

    def settings(self, **kw) -> LdapSettings:
        base = {
            "enabled": True,
            "servers": [self.server()],
            "bind_dn": SVC_DN,
            "user_search_base": f"ou=people,{BASE}",
            "group_search_base": f"ou=groups,{BASE}",
            "group_mode": "member",
            "group_roles": {ADMINS: "admin", VIEWERS: "viewer"},
            "connect_timeout_seconds": 3,
            "read_timeout_seconds": 5,
        }
        return LdapSettings.model_validate(base | kw)

    def directory(self, password: str = SVC_PW, ca: str | None = None, **kw) -> Directory:
        return Directory(self.settings(**kw), password, ca or self.ca_pem)

    def root(self) -> ldap3.Connection:
        tls = ldap3.Tls(validate=ssl.CERT_REQUIRED, ca_certs_data=self.ca_pem)
        server = ldap3.Server("localhost", port=self.ldaps_port, use_ssl=True, tls=tls)
        return ldap3.Connection(server, ROOT_DN, ROOT_PW, auto_bind=True, raise_exceptions=True)


def _seed(conn: ldap3.Connection) -> None:
    conn.add(BASE, ["dcObject", "organization"], {"dc": "acme", "o": "Acme"})
    for ou in ("people", "groups", "services", "contractors,ou=people"):
        conn.add(f"ou={ou},{BASE}", ["organizationalUnit"])
    conn.add(SVC_DN, ["organizationalRole", "simpleSecurityObject"], {"userPassword": SVC_PW})

    def person(uid: str, parent: str = f"ou=people,{BASE}") -> str:
        dn = f"uid={uid},{parent}"
        conn.add(
            dn,
            ["inetOrgPerson"],
            {"cn": uid, "sn": "Example", "displayName": uid.title(), "userPassword": USER_PW},
        )
        return dn

    avery, blake, drew, frank = person("avery"), person("blake"), person("drew"), person("frank")
    person("casey")  # in no group
    person("sam")
    person("sam", f"ou=contractors,ou=people,{BASE}")  # two entries named sam
    conn.add(OPS, ["groupOfNames"], {"member": [drew]})
    conn.add(ADMINS, ["groupOfNames"], {"member": [avery, OPS]})  # drew is admin through OPS
    conn.add(VIEWERS, ["groupOfNames"], {"member": [blake, frank]})


@pytest.fixture(scope="module")
def ldap_server(tmp_path_factory) -> Ldap:
    if shutil.which("docker") is None:
        _skip("docker is not installed")
    try:
        _docker("info", timeout=20)
    except (subprocess.SubprocessError, OSError):
        _skip("docker is not usable")
    if _docker("image", "inspect", IMAGE, check=False).returncode != 0:
        try:  # host network: the build only fetches Debian packages
            _docker("build", "--network", "host", "-t", IMAGE, str(DOCKERFILE_DIR), timeout=600)
        except subprocess.SubprocessError as e:
            _skip(f"the OpenLDAP test image did not build ({type(e).__name__})")
    cfg = tmp_path_factory.mktemp("openldap")
    ca_key, ca = make_ca("Acme Test LDAP CA")
    key, cert = make_server_cert(ca_key, ca, ["localhost"])
    (cfg / "ca.pem").write_text(pem(ca))
    (cfg / "server.pem").write_text(pem(cert))
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    )
    (cfg / "server.key").write_bytes(key_pem)
    (cfg / "slapd.conf").write_text(SLAPD_CONF)
    cfg.chmod(0o755)
    for f in cfg.iterdir():
        f.chmod(0o644)  # a throwaway test key, read by slapd in the container
    name = f"pmx-test-ldap-{uuid.uuid4().hex[:8]}"
    _docker(
        "run", "-d", "--rm", "--name", name,
        "-p", "127.0.0.1::636", "-p", "127.0.0.1::389",
        "-v", f"{cfg}:/cfg:ro", IMAGE,
    )  # fmt: skip
    try:
        ports = [int(_docker("port", name, p).stdout.split(":")[-1]) for p in ("636", "389")]
        server = Ldap(ports[0], ports[1], pem(ca))
        deadline = time.monotonic() + 40
        while True:
            try:
                root = server.root()
                break
            except ldap3.core.exceptions.LDAPException:
                if time.monotonic() > deadline:
                    logs = _docker("logs", name, check=False).stderr[-2000:]
                    pytest.fail(f"OpenLDAP did not start:\n{logs}")
                time.sleep(0.5)
        _seed(root)
        root.unbind()
        yield server
    finally:
        _docker("rm", "-f", name, check=False)


def _dead_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]  # closed again: nothing listens there


# --- TLS ------------------------------------------------------------------------------------


def test_ldaps_service_bind_and_lookup(ldap_server):
    out = ldap_server.directory().lookup("avery")
    assert out["found"] == 1 and out["role"] == "admin"
    assert out["dn"] == f"uid=avery,ou=people,{BASE}"


def test_starttls_works(ldap_server):
    server = {"url": f"ldap://localhost:{ldap_server.plain_port}", "start_tls": True}
    user = ldap_server.directory(servers=[server]).authenticate("blake", USER_PW)
    assert user.role == "viewer"


def test_plain_ldap_is_refused_at_config_and_at_connect(ldap_server):
    with pytest.raises(ValueError, match="plain LDAP is refused"):
        ldap_server.settings(servers=[{"url": f"ldap://localhost:{ldap_server.plain_port}"}])
    # Even a settings object built without validation never sends a bind in clear.
    plain = (
        ldap_server.settings()
        .servers[0]
        .model_construct(url=f"ldap://localhost:{ldap_server.plain_port}", start_tls=False)
    )
    d = ldap_server.directory()
    d.s = d.s.model_copy(update={"servers": [plain]})
    with pytest.raises(DirectoryUnavailable, match="plain_ldap_refused"):
        d.authenticate("avery", USER_PW)


def test_a_certificate_from_another_ca_is_refused(ldap_server):
    _, other = make_ca("Other CA")
    d = ldap_server.directory(ca=pem(other))
    with pytest.raises(DirectoryUnavailable):
        d.authenticate("avery", USER_PW)
    report = d.test_connection()
    assert report[0]["ok"] is False
    assert report[0]["steps"][-1]["step"] == "certificate"
    assert "certificate refused" in report[0]["steps"][-1]["detail"]


def test_the_host_name_is_checked(ldap_server):
    # The certificate names `localhost`; 127.0.0.1 is the same server but not that name.
    d = ldap_server.directory(servers=[{"url": f"ldaps://127.0.0.1:{ldap_server.ldaps_port}"}])
    with pytest.raises(DirectoryUnavailable):
        d.authenticate("avery", USER_PW)
    step = d.test_connection()[0]["steps"][-1]
    assert step["step"] == "certificate" and "mismatch" in step["detail"].lower()


def test_test_connection_reports_each_step(ldap_server):
    report = ldap_server.directory().test_connection()
    assert report[0]["ok"] is True
    steps = {s["step"]: s for s in report[0]["steps"]}
    assert set(steps) == {"connect", "tls", "certificate", "bind"}
    assert steps["certificate"]["certificate_info"]["subject"] == "CN=localhost"
    bad = ldap_server.directory(password="wrong-service-password-1")
    assert bad.test_connection()[0]["steps"][-1] == {
        "step": "bind",
        "ok": False,
        "detail": "service bind refused: check the bind DN and password",
    }


def test_tls_context_trusts_only_the_bundle(ldap_server):
    ctx = tls_context(ldap_server.ca_pem)
    assert len(ctx.get_ca_certs()) == 1 and ctx.check_hostname


# --- login flow -----------------------------------------------------------------------------


def test_empty_password_is_refused_before_any_bind(ldap_server, monkeypatch):
    binds = []
    monkeypatch.setattr(ldap3.Connection, "bind", lambda self, *a, **k: binds.append(1))
    with pytest.raises(DirectoryRefused, match="empty_password"):
        ldap_server.directory().authenticate("avery", "")
    assert binds == []


@pytest.mark.parametrize(
    "name", ["*", "ave*", "*)(uid=*", "avery)(uid=*", "avery\x00", "*)(|(uid=*"]
)
def test_filter_injection_is_refused(ldap_server, name):
    with pytest.raises(DirectoryRefused) as e:
        ldap_server.directory().authenticate(name, USER_PW)
    assert e.value.reason in ("not_found", "bad_username")


def test_exactly_one_entry(ldap_server):
    with pytest.raises(DirectoryRefused, match="ambiguous"):
        ldap_server.directory().authenticate("sam", USER_PW)
    assert ldap_server.directory().lookup("sam")["found"] == 2


def test_wrong_password_and_unknown_user(ldap_server):
    with pytest.raises(DirectoryRefused, match="bad_password"):
        ldap_server.directory().authenticate("avery", "not-the-password-1")
    with pytest.raises(DirectoryRefused, match="not_found"):
        ldap_server.directory().authenticate("ghost", USER_PW)


def test_no_mapped_group_means_no_access(ldap_server):
    with pytest.raises(DirectoryRefused, match="no_group"):
        ldap_server.directory().authenticate("casey", USER_PW)
    out = ldap_server.directory().lookup("casey")
    assert out["role"] is None and "can't sign in" in out["message"]


def test_nested_groups_through_member_search(ldap_server):
    with pytest.raises(DirectoryRefused, match="no_group"):
        ldap_server.directory(nested_groups=False).authenticate("drew", USER_PW)
    user = ldap_server.directory(nested_groups=True).authenticate("drew", USER_PW)
    assert user.role == "admin" and user.groups == (ADMINS,)


def test_member_of_mode_through_the_overlay(ldap_server):
    d = ldap_server.directory(group_mode="member_of")
    assert d.authenticate("avery", USER_PW).role == "admin"
    assert d.authenticate("blake", USER_PW).role == "viewer"


def test_failover_to_the_second_server(ldap_server):
    dead = {"url": f"ldaps://localhost:{_dead_port()}"}
    d = ldap_server.directory(servers=[dead, ldap_server.server()])
    assert d.authenticate("avery", USER_PW).role == "admin"
    report = d.test_connection()
    assert [r["ok"] for r in report] == [False, True]
    with pytest.raises(DirectoryUnavailable, match="unreachable"):
        ldap_server.directory(servers=[dead]).authenticate("avery", USER_PW)


def test_a_wrong_password_does_not_fail_over(ldap_server, monkeypatch):
    opened = []
    real = Directory._open

    def spy(self, server, user, password):
        opened.append(user)
        return real(self, server, user, password)

    monkeypatch.setattr(Directory, "_open", spy)
    second = ldap_server.server()
    d = ldap_server.directory(servers=[ldap_server.server(), second])
    with pytest.raises(DirectoryRefused, match="bad_password"):
        d.authenticate("avery", "not-the-password-1")
    assert opened == [SVC_DN, f"uid=avery,ou=people,{BASE}"]  # one user bind, one server


# --- through Auth: provisioning and a group change at the next sign-in --------------------------


def test_group_change_takes_effect_at_next_login(ldap_server, pg):
    from test_ldap import enable_ldap

    from parsemaxxing.auth.service import Auth
    from parsemaxxing.secrets import Kek
    from parsemaxxing.settings import AuthSettings

    kek = Kek(os.urandom(32))
    enable_ldap(pg.conn, kek, ldap_server.settings(), SVC_PW, ldap_server.ca_pem)
    auth = Auth(pg.conn, AuthSettings(require_mfa_admins=False), lambda: kek)
    raw, user, stage = auth.login("frank", USER_PW, "203.0.113.9", "pytest")
    assert (user["role"], user["source"], stage) == ("viewer", "ldap", "full")
    assert user["password_hash"] is None
    assert user["directory_id"].startswith("entryUUID:")  # OpenLDAP's stable identity
    old = auth.session(raw)
    assert old is not None and old.role == "viewer"

    root = ldap_server.root()
    frank = f"uid=frank,ou=people,{BASE}"
    root.modify(ADMINS, {"member": [(ldap3.MODIFY_ADD, [frank])]})
    try:
        raw2, user2, _ = Auth(pg.conn, AuthSettings(require_mfa_admins=False), lambda: kek).login(
            "frank", USER_PW, "203.0.113.9", "pytest"
        )
        assert user2["role"] == "admin" and user2["id"] == user["id"]
        assert auth.session(raw) is None  # the role change revoked the older session
        assert auth.session(raw2).role == "admin"
        root.modify(ADMINS, {"member": [(ldap3.MODIFY_DELETE, [frank])]})
        root.modify(VIEWERS, {"member": [(ldap3.MODIFY_DELETE, [frank])]})
        with pytest.raises(Exception, match="Sign-in failed"):
            Auth(pg.conn, AuthSettings(), lambda: kek).login("frank", USER_PW, "203.0.113.9", "t")
    finally:
        root.unbind()


def test_failed_sign_ins_share_one_timing_class(ldap_server, pg, monkeypatch):
    """L1 in real time: a local name, and each directory failure step (not found, wrong
    password, no group, two entries), all take the padded minimum, not their own time."""
    from conftest import make_user
    from test_ldap import enable_ldap

    from parsemaxxing.auth import service
    from parsemaxxing.auth.service import Auth
    from parsemaxxing.secrets import Kek
    from parsemaxxing.settings import AuthSettings

    monkeypatch.setattr(service, "_sleep", time.sleep)
    kek = Kek(os.urandom(32))
    enable_ldap(pg.conn, kek, ldap_server.settings(), SVC_PW, ldap_server.ca_pem)
    make_user(pg.conn, "local-timed", "viewer")
    auth = Auth(pg.conn, AuthSettings(failure_min_seconds=1.0), lambda: kek)
    took = {}
    for name, password in [
        ("local-timed", "wrong-password-123"),
        ("ghost", USER_PW),
        ("avery", "wrong-password-123"),
        ("casey", USER_PW),
        ("sam", USER_PW),
    ]:
        t = time.monotonic()
        with pytest.raises(Exception, match="Sign-in failed"):
            auth.login(name, password, "203.0.113.40", "t")
        took[name] = time.monotonic() - t
        pg.conn.execute("DELETE FROM auth_throttle")
    assert all(1.0 <= v < 1.35 for v in took.values()), took
