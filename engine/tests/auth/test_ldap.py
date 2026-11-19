"""Phase 14 LDAP logic (design 7.4, T12), adversarial, with ldap3's MOCK_SYNC strategy: RFC 4515
escaping, the exactly-one-entry rule, the empty password refused before any connection, group
modes and mapping, failover order, settings validation, the CA bundle rules, the sign-in flow
through Auth (provisioning, break-glass, lockout, role changes, MFA), the admin routes, and a
scan proving the bind password never reaches responses, audit rows, history or logs.

The real-server tests are in test_ldap_integration.py (marker ldap_integration)."""

import dataclasses
import datetime as dt
import logging
import os
import statistics
import time
import uuid

import ldap3
import pytest
from conftest import TEST_PASSWORD, WEB_ORIGIN, api_client, make_user, settings, sign_in
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from ldap3.core.exceptions import LDAPSocketOpenError

from parsemaxxing.api import app as api
from parsemaxxing.auth.ldap import (
    IN_CHAIN,
    Directory,
    DirectoryRefused,
    DirectoryUnavailable,
    check_ca_bundle,
)
from parsemaxxing.auth.model import AuthError, Principal, Role
from parsemaxxing.auth.service import LOGIN_FAILED, Auth
from parsemaxxing.secrets import Kek, Vault
from parsemaxxing.settings import PLATFORM, AuthSettings, LdapSettings, SettingsService

BASE = "dc=acme,dc=example"
SVC_DN = f"cn=pmx-svc,ou=services,{BASE}"
SVC_PW = "svc-mock-secret-9d41e7"  # gitleaks:allow
USER_PW = "user-mock-pass-55c2"  # gitleaks:allow
ADMINS = f"cn=pmx-admins,ou=groups,{BASE}"
VIEWERS = f"cn=pmx-viewers,ou=groups,{BASE}"
OPS = f"cn=ops-team,ou=groups,{BASE}"
URLS = ["ldaps://ldap1.acme.example", "ldaps://ldap2.acme.example", "ldaps://ldap3.acme.example"]


def dn(uid: str) -> str:
    return f"uid={uid},ou=people,{BASE}"


class Dit:
    """A mock directory shared by every connection, with a scripted transport per server."""

    def __init__(self):
        self.server = ldap3.Server("mock", get_info=ldap3.NONE)
        self.seed = ldap3.Connection(self.server, client_strategy=ldap3.MOCK_SYNC)
        self.down: set[str] = set()
        self.opened: list[tuple[str, str]] = []  # (url, bind user)
        self.uuids: dict[str, str] = {}
        add = self.seed.strategy.add_entry
        add(SVC_DN, {"objectClass": "organizationalRole", "userPassword": SVC_PW})
        for uid, groups in [
            ("avery", [ADMINS]),
            ("blake", [VIEWERS]),
            ("both", [VIEWERS, ADMINS]),
            ("casey", []),
            ("drew", [OPS]),
        ]:
            self.person(uid, groups)
        add(f"uid=sam,ou=people,{BASE}", {"uid": "sam", "userPassword": USER_PW})
        add(f"uid=sam,ou=contractors,{BASE}", {"uid": "sam", "userPassword": USER_PW})
        add(f"uid=odd,ou=people,{BASE}", {"uid": "Not A Name!", "userPassword": USER_PW})
        add(OPS, {"objectClass": "groupOfNames", "member": [dn("drew")]})
        add(ADMINS, {"objectClass": "groupOfNames", "member": [dn("avery"), dn("both"), OPS]})
        add(VIEWERS, {"objectClass": "groupOfNames", "member": [dn("blake"), dn("both")]})

    def person(self, rdn: str, groups: list[str], **attrs) -> None:
        self.seed.strategy.add_entry(
            dn(rdn),
            {
                "objectClass": "inetOrgPerson",
                "uid": rdn,
                "displayName": rdn.title(),
                "userPassword": USER_PW,
                "memberOf": groups,
                # stable per name unless a test re-creates the entry with a new one
                "entryUUID": self.uuids.setdefault(rdn, attrs.pop("entryUUID", str(uuid.uuid4()))),
                **attrs,
            },
        )

    def set_groups(self, uid: str, groups: list[str]) -> None:
        self.seed.strategy.remove_entry(dn(uid))
        self.person(uid, groups)

    def connect(self, server, user, password):
        self.opened.append((server.url, user))
        if server.url in self.down:
            raise LDAPSocketOpenError("unreachable")
        conn = ldap3.Connection(
            self.server,
            user=user,
            password=password,
            client_strategy=ldap3.MOCK_SYNC,
            raise_exceptions=False,
        )
        conn.open()
        return conn, None


def ldap_settings(**kw) -> LdapSettings:
    base = {
        "enabled": True,
        "servers": [{"url": u} for u in URLS[:2]],
        "bind_dn": SVC_DN,
        "user_search_base": BASE,
        "group_search_base": f"ou=groups,{BASE}",
        "group_mode": "member_of",
        "group_roles": {ADMINS: "admin", VIEWERS: "viewer"},
    }
    return LdapSettings.model_validate(base | kw)


@pytest.fixture
def dit():
    return Dit()


def directory(dit: Dit, password: str = SVC_PW, **kw) -> Directory:
    return Directory(ldap_settings(**kw), password, "", dit.connect)


# --- escaping and the exactly-one rule (T12.2) ------------------------------------------------


@pytest.mark.parametrize(
    ("name", "sent"),
    [
        ("*", r"(uid=\2a)"),
        ("*)(uid=*", r"(uid=\2a\29\28uid=\2a)"),
        ("avery)(|(uid=*", r"(uid=avery\29\28|\28uid=\2a)"),
        ("a\\b", r"(uid=a\5cb)"),
    ],
)
def test_the_username_is_escaped_per_rfc4515(dit, monkeypatch, name, sent):
    filters = []
    real = ldap3.Connection.search

    def spy(self, base, flt, *a, **k):
        filters.append(flt)
        return real(self, base, flt, *a, **k)

    monkeypatch.setattr(ldap3.Connection, "search", spy)
    with pytest.raises(DirectoryRefused, match="not_found"):
        directory(dit).authenticate(name, USER_PW)
    assert filters == [sent]


@pytest.mark.parametrize("name", ["avery\x00", "avery\n", "", "x" * 257])
def test_control_characters_and_odd_lengths_never_reach_the_directory(dit, name):
    with pytest.raises(DirectoryRefused, match="bad_username"):
        directory(dit).authenticate(name, USER_PW)
    assert dit.opened == []


def test_exactly_one_entry_or_fail(dit):
    with pytest.raises(DirectoryRefused, match="ambiguous"):
        directory(dit).authenticate("sam", USER_PW)
    with pytest.raises(DirectoryRefused, match="not_found"):
        directory(dit).authenticate("ghost", USER_PW)
    assert directory(dit).lookup("sam")["found"] == 2
    assert directory(dit).lookup("sam")["dn"] is None  # never one of the two


def test_a_directory_name_that_is_not_a_usable_local_name_is_refused(dit):
    with pytest.raises(DirectoryRefused, match="unusable_name"):
        directory(dit).authenticate("Not A Name!", USER_PW)


# --- the empty password (T12.3) -------------------------------------------------------------


def test_empty_password_is_refused_before_any_connection(dit):
    with pytest.raises(DirectoryRefused, match="empty_password"):
        directory(dit).authenticate("avery", "")
    assert dit.opened == []


def test_empty_password_is_refused_at_the_bind_helper_too(dit):
    """Defense in depth: the bind helper refuses an empty password whoever calls it."""
    with pytest.raises(DirectoryRefused, match="empty_password"):
        directory(dit)._bound(dn("avery"), "", service=False)
    with pytest.raises(DirectoryUnavailable, match="service_bind_refused"):
        directory(dit, password="").lookup("avery")  # an empty stored service password
    assert dit.opened == []


# --- groups and mapping (T12.4) -------------------------------------------------------------


@pytest.mark.parametrize("mode", ["member_of", "member"])
def test_group_modes_and_highest_role(dit, mode):
    d = directory(dit, group_mode=mode)
    assert d.authenticate("avery", USER_PW).role == "admin"
    assert d.authenticate("blake", USER_PW).role == "viewer"
    both = d.authenticate("both", USER_PW)
    assert both.role == "admin" and set(both.groups) == {ADMINS, VIEWERS}
    for uid in ("casey", "drew"):  # no group / only an unmapped group (no nesting)
        with pytest.raises(DirectoryRefused, match="no_group"):
            d.authenticate(uid, USER_PW)


def test_nested_groups_in_member_mode(dit):
    user = directory(dit, group_mode="member", nested_groups=True).authenticate("drew", USER_PW)
    assert user.role == "admin" and user.groups == (ADMINS,)


def test_nested_groups_stop_at_a_cycle(dit):
    dit.seed.strategy.add_entry(
        f"cn=loop-a,ou=groups,{BASE}",
        {"objectClass": "groupOfNames", "member": [dn("casey"), f"cn=loop-b,ou=groups,{BASE}"]},
    )
    dit.seed.strategy.add_entry(
        f"cn=loop-b,ou=groups,{BASE}",
        {"objectClass": "groupOfNames", "member": [f"cn=loop-a,ou=groups,{BASE}"]},
    )
    with pytest.raises(DirectoryRefused, match="no_group"):
        directory(dit, group_mode="member", nested_groups=True).authenticate("casey", USER_PW)


def test_ad_nested_mode_uses_the_in_chain_rule_with_an_escaped_dn(dit, monkeypatch):
    """Mock-tested only: OpenLDAP has no LDAP_MATCHING_RULE_IN_CHAIN."""
    dit.person("par(en)*", [], uid="paren")
    seen = []

    def paged(self, conn, flt):
        seen.append(flt)
        return [ADMINS]

    monkeypatch.setattr(Directory, "_paged", paged)
    user = directory(dit, group_mode="ad_nested").authenticate("paren", USER_PW)
    assert user.role == "admin"
    assert seen == [rf"(member:{IN_CHAIN}:=uid=par\28en\29\2a,ou=people,{BASE})"]


def test_group_dns_match_case_insensitively(dit):
    d = directory(dit, group_roles={ADMINS.upper(): "admin"})
    assert d.authenticate("avery", USER_PW).role == "admin"


def test_member_mode_escapes_the_user_dn(dit, monkeypatch):
    dit.person("x*)(member=*", [], uid="star")
    seen = []
    monkeypatch.setattr(Directory, "_paged", lambda self, conn, flt: seen.append(flt) or [])
    with pytest.raises(DirectoryRefused, match="no_group"):
        directory(dit, group_mode="member").authenticate("star", USER_PW)
    value = seen[0].removeprefix("(member=").removesuffix(")")
    assert seen[0].startswith("(member=uid=x\\2a\\29\\28member") and not set("*()") & set(value)


# --- servers: failover and the service bind ---------------------------------------------------


def test_failover_in_order_then_stays_on_the_server_that_answered(dit):
    dit.down = {URLS[0]}
    d = Directory(ldap_settings(servers=[{"url": u} for u in URLS]), SVC_PW, "", dit.connect)
    assert d.authenticate("avery", USER_PW).role == "admin"
    assert [u for u, _ in dit.opened] == [URLS[0], URLS[1], URLS[1]]  # service, then user bind
    dit.opened.clear()
    d.authenticate("blake", USER_PW)
    assert [u for u, _ in dit.opened] == [URLS[1], URLS[1]]


def test_every_server_down_is_unavailable(dit):
    dit.down = set(URLS)
    with pytest.raises(DirectoryUnavailable, match="unreachable"):
        directory(dit).authenticate("avery", USER_PW)
    assert [u for u, _ in dit.opened] == URLS[:2]


def test_a_wrong_user_password_does_not_fail_over(dit):
    with pytest.raises(DirectoryRefused, match="bad_password"):
        directory(dit).authenticate("avery", "wrong-password-123")
    assert [who for _, who in dit.opened] == [SVC_DN, dn("avery")]


def test_a_refused_service_bind_is_unavailable_not_a_user_failure(dit):
    with pytest.raises(DirectoryUnavailable, match="service_bind_refused"):
        directory(dit, password="not-the-service-pw").authenticate("avery", USER_PW)


def test_test_connection_and_lookup_steps(dit):
    dit.down = {URLS[0]}
    report = directory(dit).test_connection()
    assert [r["ok"] for r in report] == [False, True]
    assert report[0]["steps"] == [
        {
            "step": "connect",
            "ok": False,
            "detail": "could not connect (refused, unreachable or timed out)",
        }
    ]
    assert [s["step"] for s in report[1]["steps"]] == ["connect", "tls", "certificate", "bind"]
    out = directory(dit).lookup("avery")
    assert set(out) == {"found", "dn", "matched_groups", "role", "message"}  # no attributes
    assert out == out | {"found": 1, "dn": dn("avery"), "role": "admin"}
    assert "can't sign in" in directory(dit).lookup("casey")["message"]


# --- settings and CA bundle ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "server",
    [
        {"url": "ldap://ldap.acme.example"},  # plain LDAP
        {"url": "ldap://ldap.acme.example", "start_tls": False},
        {"url": "ldaps://ldap.acme.example", "start_tls": True},
        {"url": "http://ldap.acme.example"},
        {"url": "ldaps://svc:pw@ldap.acme.example"},
        {"url": "ldaps://ldap.acme.example/dc=acme"},
        {"url": "ldaps://ldap.acme.example:0x1"},
    ],
)
def test_insecure_or_odd_server_urls_are_refused(server):
    with pytest.raises(ValueError):
        ldap_settings(servers=[server])


@pytest.mark.parametrize(
    "flt",
    [
        "uid={username}",
        "(uid={username})(uid=*)",
        "(uid={user})",
        "(|(uid={username})(cn={0}))",
        "(uid={username})\n",
        "(uid=admin)",
    ],
)
def test_bad_filter_templates_are_refused(flt):
    with pytest.raises(ValueError):
        ldap_settings(user_filter=flt)


def test_dns_and_mapping_are_validated():
    with pytest.raises(ValueError):
        ldap_settings(bind_dn="not a dn")
    with pytest.raises(ValueError):
        ldap_settings(group_roles={ADMINS: "superuser"})
    with pytest.raises(ValueError):
        ldap_settings(group_roles={"cn=x\n,dc=y": "admin"})
    assert LdapSettings().missing_for_enable() == [
        "servers",
        "ca_bundle",
        "bind_dn",
        "bind_password",
        "user_search_base",
        "group_roles",
    ]


def _cert(ca: bool = True, days: int = 30, cn: str = "Acme Test CA"):
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    now = dt.datetime.now(dt.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=60))
        .not_valid_after(now + dt.timedelta(days=days))
        .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    return key, cert.public_bytes(serialization.Encoding.PEM).decode()


def test_ca_bundle_rules():
    key, good = _cert()
    out = check_ca_bundle(good)
    assert out[0]["subject"] == "CN=Acme Test CA" and len(out[0]["sha256"]) == 64
    key_pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    for bad, why in [
        (good + key_pem, "only certificates"),  # a pasted private key is refused
        ("hello", "no PEM"),
        (_cert(ca=False)[1], "not a CA"),
        (_cert(days=-1)[1], "expired"),
        (good.replace(good.splitlines()[2], "A" * 64), "not valid"),
    ]:
        with pytest.raises(ValueError, match=why):
            check_ca_bundle(bad)


# --- through Auth --------------------------------------------------------------------------------


def enable_ldap(conn, kek: Kek, s: LdapSettings, bind_pw: str = SVC_PW, ca: str = "") -> None:
    vault = Vault(conn, kek)
    values = s.model_dump(mode="json", exclude=LdapSettings.secret_fields())
    values["bind_password"] = vault.put(PLATFORM, "ldap.bind_password", bind_pw, "test")
    values["ca_bundle"] = vault.put(PLATFORM, "ldap.ca_bundle", ca or _cert()[1], "test")
    conn.execute("DELETE FROM settings_groups WHERE grp = 'ldap'")
    SettingsService(conn, {}).set(LdapSettings, PLATFORM, values, "test")


@pytest.fixture
def kek():
    return Kek(os.urandom(32))


@pytest.fixture
def ldap_on(pg, kek, dit, monkeypatch):
    enable_ldap(pg.conn, kek, ldap_settings())
    monkeypatch.setattr(Auth, "ldap_connect", staticmethod(dit.connect))
    yield dit
    pg.conn.execute("DELETE FROM settings_groups WHERE grp = 'ldap'")


def auth(pg, kek, **kw) -> Auth:
    return Auth(pg.conn, AuthSettings(**({"require_mfa_admins": False} | kw)), lambda: kek)


def test_ldap_login_provisions_a_password_less_local_row(pg, kek, ldap_on):
    raw, user, stage = auth(pg, kek).login("Avery", USER_PW, "203.0.113.5", "pytest")
    assert (user["username"], user["source"], user["role"], stage) == (
        "avery",
        "ldap",
        "admin",
        "full",
    )
    assert user["password_hash"] is None and user["display_name"] == "Avery"
    assert auth(pg, kek).session(raw).role == Role.ADMIN
    _, again, _ = auth(pg, kek).login("avery", USER_PW, "203.0.113.5", "pytest")
    assert again["id"] == user["id"]  # same row at the next sign-in
    rows = pg.conn.execute("SELECT count(*) AS n FROM users WHERE source = 'ldap'").fetchone()
    assert rows["n"] == 1


@pytest.mark.parametrize(
    ("name", "password"),
    [
        ("avery", "wrong-password-123"),
        ("ghost", USER_PW),
        ("casey", USER_PW),  # no mapped group
        ("sam", USER_PW),  # two entries
        ("*", USER_PW),
        ("avery", ""),
    ],
)
def test_every_directory_failure_is_the_generic_one(pg, kek, ldap_on, name, password):
    with pytest.raises(AuthError) as e:
        auth(pg, kek).login(name, password, "203.0.113.6", "pytest")
    assert (e.value.status, e.value.message) == (401, LOGIN_FAILED)
    row = pg.conn.execute(
        "SELECT actor, detail FROM auth_events WHERE event = 'login' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row["detail"]["source"] == "ldap" and row["detail"]["reason"]
    assert name not in str(row) or name == "avery"  # a typed unknown name is never stored


def test_directory_failures_take_the_local_timing_class(pg, kek, ldap_on):
    a = auth(pg, kek)
    make_user(pg.conn, "timed-local", "viewer")

    def took(name: str) -> float:
        t = time.perf_counter()
        with pytest.raises(AuthError):
            a.login(name, "wrong-password-123", "203.0.113.7", "t")
        a.conn.execute("DELETE FROM auth_throttle")
        return time.perf_counter() - t

    local = statistics.median(took("timed-local") for _ in range(5))
    directory_ = statistics.median(took(n) for n in ("ghost", "casey", "avery", "sam", "nobody"))
    assert 0.5 < directory_ / local < 2.0  # Argon2 dominates both; the mock is fast


def test_directory_failures_lock_out_like_local_ones(pg, kek, ldap_on):
    a = auth(pg, kek)
    for _ in range(5):
        with pytest.raises(AuthError, match="Sign-in failed"):
            a.login("avery", "wrong-password-123", "203.0.113.8", "t")
    with pytest.raises(AuthError) as e:
        a.login("avery", USER_PW, "203.0.113.8", "t")  # right password, still locked
    assert e.value.status == 429


def test_local_accounts_never_touch_the_directory_and_work_when_it_is_down(pg, kek, ldap_on):
    make_user(pg.conn, "breakglass", "admin")
    ldap_on.down = set(URLS)
    a = auth(pg, kek)
    for _ in range(25):  # an outage is not counted: shared IPs keep the break-glass usable
        with pytest.raises(AuthError, match="Sign-in failed"):
            a.login("avery", USER_PW, "203.0.113.10", "t")
    ldap_on.opened.clear()
    _, user, _ = a.login("breakglass", TEST_PASSWORD, "203.0.113.10", "t")
    assert user["source"] == "local" and ldap_on.opened == []
    events = pg.conn.execute(
        "SELECT detail FROM auth_events WHERE event = 'login' AND outcome = 'failure'"
    ).fetchall()
    assert {e["detail"]["reason"] for e in events} == {"unreachable"}


def test_a_directory_name_cannot_take_over_a_local_account(pg, kek, ldap_on):
    make_user(pg.conn, "avery", "viewer")  # a local account with the directory user's name
    enable_ldap(pg.conn, kek, ldap_settings(user_filter="(|(uid={username})(mail={username}))"))
    ldap_on.seed.strategy.remove_entry(dn("avery"))
    ldap_on.person("avery", [ADMINS], mail="avery@acme.example")
    with pytest.raises(AuthError, match="Sign-in failed"):
        auth(pg, kek).login("avery@acme.example", USER_PW, "203.0.113.11", "t")
    row = pg.conn.execute("SELECT * FROM users WHERE username = 'avery'").fetchone()
    assert (row["source"], row["role"]) == ("local", "viewer")
    reason = pg.conn.execute(
        "SELECT detail->>'reason' AS r FROM auth_events WHERE event = 'login' ORDER BY id DESC"
    ).fetchone()["r"]
    assert reason == "local_name_conflict"


def test_ldap_off_means_directory_rows_cannot_sign_in(pg, kek, ldap_on):
    auth(pg, kek).login("avery", USER_PW, "203.0.113.12", "t")
    SettingsService(pg.conn, {}).set(LdapSettings, PLATFORM, {"enabled": False}, "test")
    with pytest.raises(AuthError, match="Sign-in failed"):
        auth(pg, kek).login("avery", USER_PW, "203.0.113.12", "t")


def test_group_change_takes_effect_at_next_login_and_revokes_old_sessions(pg, kek, ldap_on):
    raw, user, _ = auth(pg, kek).login("blake", USER_PW, "203.0.113.13", "t")
    assert user["role"] == "viewer"
    ldap_on.set_groups("blake", [ADMINS])
    raw2, user2, _ = auth(pg, kek).login("blake", USER_PW, "203.0.113.13", "t")
    assert user2["role"] == "admin"
    assert auth(pg, kek).session(raw) is None and auth(pg, kek).session(raw2).role == Role.ADMIN
    change = pg.conn.execute(
        "SELECT actor, detail FROM auth_events WHERE event = 'role_change'"
    ).fetchone()
    assert change["actor"] == "ldap" and change["detail"]["new"] == "admin"
    ldap_on.set_groups("blake", [])
    with pytest.raises(AuthError, match="Sign-in failed"):
        auth(pg, kek).login("blake", USER_PW, "203.0.113.13", "t")


def test_ldap_sessions_end_at_the_absolute_timeout(pg, kek, ldap_on):
    raw, user, _ = auth(pg, kek).login("blake", USER_PW, "203.0.113.14", "t")
    pg.conn.execute(
        "UPDATE sessions SET expires_at = now() - interval '1 second' WHERE user_id = %s",
        (user["id"],),
    )
    assert auth(pg, kek).session(raw) is None  # then the next sign-in re-reads the groups


def test_directory_users_get_no_tokens_no_local_password_and_no_manual_role(pg, kek, ldap_on):
    _, user, _ = auth(pg, kek).login("avery", USER_PW, "203.0.113.15", "t")
    p = Principal(str(user["id"]), "avery", Role.ADMIN, "session", "full", "x")
    a = auth(pg, kek)
    with pytest.raises(AuthError, match="local accounts"):
        a.create_token(p, "ci", Role.VIEWER, 30, "t")
    with pytest.raises(AuthError, match="directory"):
        a.change_password(p, USER_PW, "a-new-password-for-me-7", "t")
    admin = make_user(pg.conn, "local-admin", "admin")
    q = Principal(str(admin["id"]), "local-admin", Role.ADMIN, "session", "full", "y")
    with pytest.raises(AuthError, match="groups"):
        a.set_role(q, str(user["id"]), Role.VIEWER, "t")
    # A directory admin is not a break-glass admin: the last local admin stays.
    with pytest.raises(AuthError, match="at least one active admin"):
        a.set_disabled(q, str(admin["id"]), True, "t")


def test_admin_reset_only_resets_local_accounts(pg, kek, ldap_on):
    from parsemaxxing.auth.service import admin_reset

    auth(pg, kek).login("avery", USER_PW, "203.0.113.16", "t")
    with pytest.raises(AuthError, match="no local user"):
        admin_reset(pg.conn, "avery", "a-new-password-for-me-7")


def test_mfa_for_directory_users(pg, kek, ldap_on):
    _, _, stage = auth(pg, kek, require_mfa_admins=True).login(
        "avery", USER_PW, "203.0.113.17", "t"
    )
    assert stage == "enrol"  # "require MFA for admins" covers directory admins too
    _, _, stage = auth(pg, kek).login("blake", USER_PW, "203.0.113.17", "t")
    assert stage == "full"
    enable_ldap(pg.conn, kek, ldap_settings(require_mfa=True))
    _, user, stage = auth(pg, kek).login("blake", USER_PW, "203.0.113.17", "t")
    assert stage == "enrol"
    # Enrolment on a full session re-checks the password with the directory.
    p = Principal(str(user["id"]), "blake", Role.VIEWER, "session", "full", "z")
    with pytest.raises(AuthError, match="not correct"):
        auth(pg, kek).mfa_enrol(p, "t", "wrong-password-123")
    assert "secret" in auth(pg, kek).mfa_enrol(p, "t", USER_PW)


# --- admin routes ---------------------------------------------------------------------------


@pytest.fixture
def app(pg, pg_dsn, tmp_path, kek):
    s = dataclasses.replace(settings(tmp_path), runs_dir=tmp_path / "runs")
    pg.conn.execute("DELETE FROM settings_groups WHERE grp IN ('auth', 'ldap')")
    return api.create_app(s, dsn=pg_dsn, migrate=True, kek=kek)


@pytest.fixture
def admin(app, pg, dit, monkeypatch):
    monkeypatch.setattr(Auth, "ldap_connect", staticmethod(dit.connect))
    with api_client(app) as c:
        sign_in(c, pg.conn, "ldap-admin", "admin")
        yield c


def _put(client, **body):
    return client.put("/auth/ldap", json=body)


REAUTH = {"bind_password": SVC_PW, "current_password": TEST_PASSWORD}


def _upload_ca(client, pem: str | None = None, **body):
    return client.post("/auth/ldap/ca-bundle", json={"pem": pem or _cert()[1]} | REAUTH | body)


def _full_config(client) -> None:
    r = _upload_ca(client)
    assert r.status_code == 200, r.text
    values = ldap_settings().model_dump(mode="json", exclude=LdapSettings.secret_fields())
    r = _put(client, settings=values, **REAUTH)
    assert r.status_code == 200, r.text


def test_ldap_settings_round_trip_without_the_bind_password(admin, pg, caplog):
    caplog.set_level(logging.DEBUG)
    r = admin.get("/auth/ldap")
    assert r.status_code == 200 and r.json()["bind_password_set"] is False
    assert r.json()["local_admins"] == ["ldap-admin"]
    _full_config(admin)
    body = admin.get("/auth/ldap").json()
    assert body["bind_password_set"] is True and body["settings"]["enabled"] is True
    assert "bind_password" not in body["settings"] and "ca_bundle" not in body["settings"]
    assert body["ca_bundle"][0]["subject"] == "CN=Acme Test CA"
    assert body["missing_for_enable"] == []
    lookup = admin.post("/auth/ldap/test-user-lookup", json={"username": "avery"})
    conn = admin.post("/auth/ldap/test-connection")
    assert lookup.json()["role"] == "admin" and conn.json()["ok"] is True
    # The scan: the bind password is nowhere a client, an auditor or a log reader can see.
    seen = [r.text, body, lookup.text, conn.text, caplog.text]
    seen += [str(x) for x in pg.conn.execute("SELECT * FROM auth_events").fetchall()]
    seen += [str(x) for x in pg.conn.execute("SELECT * FROM settings_history").fetchall()]
    seen += [str(x) for x in pg.conn.execute("SELECT * FROM settings_groups").fetchall()]
    assert not [s for s in seen if SVC_PW in str(s)]
    history = pg.conn.execute(
        "SELECT redacted, new_value FROM settings_history WHERE grp = 'ldap'"
        " AND field = 'bind_password'"
    ).fetchone()
    assert history["redacted"] is True and history["new_value"] is None
    audit = pg.conn.execute(
        "SELECT detail FROM auth_events WHERE event = 'ldap_settings_change'"
    ).fetchone()
    assert "bind_password" in audit["detail"]["fields"]


def test_ldap_settings_refusals(admin):
    r = _put(admin, settings={"servers": [{"url": "ldap://ldap.acme.example"}]}, **REAUTH)
    assert r.status_code == 422 and "plain LDAP is refused" in r.json()["error"]["message"]
    r = _put(admin, settings={"enabled": True})
    assert r.status_code == 422 and "servers" in r.json()["error"]["message"]
    r = _put(admin, settings={"bind_password": "00000000-0000-0000-0000-000000000000"})
    assert r.status_code == 422
    r = _put(admin, settings={"page_size": 0})
    assert r.status_code == 422 and "page_size" in r.json()["error"]["message"]
    r = _put(admin, settings={"page_size": 100}, expected_version=99)
    assert r.status_code == 409
    key, good = _cert()
    pem_key = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    r = _upload_ca(admin, good + pem_key)
    assert r.status_code == 422 and "PRIVATE" not in r.text
    r = admin.post("/auth/ldap/test-connection")
    assert r.status_code == 409  # nothing configured yet


def test_ldap_routes_need_an_admin_session(app, pg):
    from parsemaxxing.auth.service import Auth as A

    user = make_user(pg.conn, "tok-admin", "admin")
    raw, _ = A(pg.conn, AuthSettings()).create_token(
        Principal(str(user["id"]), "tok-admin", Role.ADMIN, "session", "full", "s"),
        "ci",
        Role.ADMIN,
        1,
        "t",
    )
    with api_client(app) as c:
        for method, path in [("GET", "/auth/ldap"), ("POST", "/auth/ldap/test-connection")]:
            r = c.request(method, path, headers={"Authorization": f"Bearer {raw}"})
            assert r.status_code == 403
        sign_in(c, pg.conn, "ldap-viewer", "viewer")
        assert c.get("/auth/ldap").status_code == 403
        assert c.put("/auth/ldap", json={}).status_code == 403


def test_directory_down_shows_a_reason_code_to_the_admin_only(admin, dit):
    _full_config(admin)
    dit.down = set(URLS)
    r = admin.post("/auth/ldap/test-user-lookup", json={"username": "avery"})
    assert r.status_code == 503 and "unreachable" in r.json()["error"]["message"]
    with api_client(admin.app) as anon:
        r = anon.post("/auth/login", json={"username": "avery", "password": USER_PW})
    assert r.status_code == 401 and r.json()["error"]["message"] == LOGIN_FAILED


def test_ldap_user_signs_in_through_the_api(admin, dit):
    _full_config(admin)
    with api_client(admin.app) as c:
        r = c.post("/auth/login", json={"username": "blake", "password": USER_PW})
        assert r.status_code == 200, r.text
        me = c.get("/auth/me").json()
        assert me["user"]["source"] == "ldap" and me["user"]["role"] == "viewer"
        assert me["mfa_required"] is False
        r = c.post("/auth/tokens", json={"name": "ci", "role": "viewer", "expires_in_days": 5})
        assert r.status_code == 403


# --- appsec follow-ups (M1, M2, L1 to L7) ----------------------------------------------------


def test_changing_servers_needs_the_bind_password_again_and_reauthentication(admin, pg, ldap_on):
    """M1: repointing the directory must never send the stored bind password elsewhere."""
    _full_config(admin)
    evil = {"servers": [{"url": "ldaps://attacker.example.net"}]}
    r = _put(admin, settings=evil)
    assert r.status_code == 422 and "bind password again" in r.json()["error"]["message"]
    r = _put(admin, settings=evil, bind_password=SVC_PW)
    assert r.status_code == 422 and "your own current password" in r.json()["error"]["message"]
    r = _put(admin, settings=evil, bind_password=SVC_PW, current_password="wrong-password-123")
    assert r.status_code == 403
    for body in ({}, {"bind_password": SVC_PW}):  # the CA route too
        assert _upload_ca(
            admin, **body | {"current_password": "wrong-password-123"}
        ).status_code in (
            403,
            422,
        )
    # Unchanged servers: other fields need neither.
    assert _put(admin, settings={"page_size": 200}).status_code == 200
    r = _put(admin, settings=evil, **REAUTH)
    assert r.status_code == 200
    audit = pg.conn.execute(
        "SELECT detail FROM auth_events WHERE event = 'ldap_settings_change' ORDER BY id DESC"
    ).fetchone()["detail"]
    assert audit["servers"] == ["ldaps://attacker.example.net"]
    assert SVC_PW not in str(audit)


def test_ca_upload_is_versioned(admin):
    _full_config(admin)
    assert _upload_ca(admin, expected_version=1).status_code == 409
    version = admin.get("/auth/ldap").json()["version"]
    assert _upload_ca(admin, expected_version=version).status_code == 200


def test_endpoint_change_or_disable_revokes_directory_sessions(admin, pg, kek):
    _full_config(admin)
    a = Auth(pg.conn, AuthSettings(require_mfa_admins=False), admin.app.state.kek)
    raw, _, _ = a.login("blake", USER_PW, "203.0.113.30", "t")
    local = a.new_session(make_user(pg.conn, "local-v", "viewer")["id"], "full", "t", "t")
    assert _upload_ca(admin).status_code == 200
    assert a.session(raw) is None and a.session(local) is not None
    raw, _, _ = a.login("blake", USER_PW, "203.0.113.30", "t")
    assert _put(admin, settings={"enabled": False}).status_code == 200
    assert a.session(raw) is None and a.session(local) is not None


def test_directory_sessions_are_capped(pg, kek, ldap_on):
    enable_ldap(pg.conn, kek, ldap_settings(session_max_hours=2))
    _, user, _ = auth(pg, kek, absolute_timeout_hours=12).login("blake", USER_PW, "t", "t")
    left = pg.conn.execute(
        "SELECT extract(epoch FROM expires_at - now()) AS s FROM sessions WHERE user_id = %s",
        (user["id"],),
    ).fetchone()["s"]
    assert 2 * 3600 - 60 < left <= 2 * 3600


def test_the_directory_identity_is_bound_at_first_sign_in(pg, kek, ldap_on):
    """M2: a re-created entry that reuses a user name never inherits the old row."""
    _, user, _ = auth(pg, kek).login("blake", USER_PW, "203.0.113.31", "t")
    assert user["directory_id"].startswith("entryUUID:")
    ldap_on.seed.strategy.remove_entry(dn("blake"))
    del ldap_on.uuids["blake"]
    ldap_on.person("blake", [ADMINS], entryUUID=str(uuid.uuid4()))  # a new entry, same uid
    with pytest.raises(AuthError, match="Sign-in failed"):
        auth(pg, kek).login("blake", USER_PW, "203.0.113.31", "t")
    reason = pg.conn.execute(
        "SELECT detail->>'reason' AS r FROM auth_events WHERE event = 'login' ORDER BY id DESC"
    ).fetchone()["r"]
    assert reason == "identity_mismatch"
    row = pg.conn.execute("SELECT role FROM users WHERE id = %s", (user["id"],)).fetchone()
    assert row["role"] == "viewer"  # nothing of the new entry reached the old row


def test_identity_falls_back_to_object_guid_then_the_dn():
    from parsemaxxing.auth.ldap import identity_of

    guid = uuid.uuid4()
    assert identity_of({"dn": "x", "raw_attributes": {"objectGUID": [guid.bytes_le]}}) == (
        f"objectGUID:{guid}"
    )
    assert identity_of({"dn": "UID=A,DC=Acme", "attributes": {}}) == "dn:uid=a,dc=acme"


def test_failed_sign_ins_are_padded_to_the_minimum(pg, kek, ldap_on, monkeypatch):
    """L1: local and directory failures take the same minimum time; a success is not held."""
    from parsemaxxing.auth import service

    monkeypatch.setattr(service, "_sleep", time.sleep)
    make_user(pg.conn, "pad-local", "viewer")
    a = auth(pg, kek, failure_min_seconds=1.5)
    took = []
    for name in ("pad-local", "ghost", "avery", "casey", "sam"):
        t = time.monotonic()
        with pytest.raises(AuthError):
            a.login(name, "wrong-password-123", "203.0.113.32", "t")
        took.append(time.monotonic() - t)
        pg.conn.execute("DELETE FROM auth_throttle")
    assert all(1.5 <= x < 2.2 for x in took), took
    t = time.monotonic()
    a.login("blake", USER_PW, "203.0.113.32", "t")
    assert time.monotonic() - t < 1.5


@pytest.mark.parametrize("password", ["pass\x00word-1234", "pass\nword-12345", "\u00ad"])
def test_passwords_failing_saslprep_never_reach_the_directory(dit, password):
    """L2: control characters and SASLprep failures are refused before any connection."""
    with pytest.raises(DirectoryRefused):
        directory(dit).authenticate("avery", password)
    assert dit.opened == []


def test_a_bad_password_text_counts_towards_lockout(pg, kek, ldap_on):
    a = auth(pg, kek)
    for _ in range(5):
        with pytest.raises(AuthError, match="Sign-in failed"):
            a.login("avery", "bad\x07password-1", "203.0.113.33", "t")
    with pytest.raises(AuthError) as e:
        a.login("avery", USER_PW, "203.0.113.33", "t")
    assert e.value.status == 429


@pytest.mark.parametrize("result", ["unwillingToPerform", "constraintViolation", "busy"])
def test_any_user_bind_result_is_an_answer_not_a_failover(dit, monkeypatch, result):
    """L3: only transport errors move to the next server."""
    real = ldap3.Connection.bind

    def bind(self, *a, **k):
        if self.user == dn("avery"):
            self.result = {"description": result}
            return False
        return real(self, *a, **k)

    monkeypatch.setattr(ldap3.Connection, "bind", bind)
    with pytest.raises(DirectoryRefused, match=f"bind_refused:{result}"):
        directory(dit).authenticate("avery", USER_PW)
    assert [who for _, who in dit.opened] == [SVC_DN, dn("avery")]


def test_any_service_bind_result_is_unavailable_without_failover(dit, monkeypatch):
    def bind(self, *a, **k):
        self.result = {"description": "unwillingToPerform"}
        return False

    monkeypatch.setattr(ldap3.Connection, "bind", bind)
    with pytest.raises(DirectoryUnavailable, match="service_bind_refused:unwillingToPerform"):
        directory(dit).authenticate("avery", USER_PW)
    assert len(dit.opened) == 1


def test_a_server_size_limit_stop_is_ambiguous(dit, monkeypatch):
    """L4: a server that stops at its size limit after one entry still found more than one."""
    real = ldap3.Connection.search

    def search(self, *a, **k):
        out = real(self, *a, **k)
        if self.result and self.response:
            self.result = dict(self.result, description="sizeLimitExceeded")
        return out

    monkeypatch.setattr(ldap3.Connection, "search", search)
    with pytest.raises(DirectoryRefused, match="ambiguous"):
        directory(dit).authenticate("avery", USER_PW)
    assert directory(dit).lookup("avery")["found"] == 2


def test_lockout_also_counts_per_directory_identity(pg, kek, ldap_on):
    """L5: two typed names for one entry share the entry's lockout."""
    enable_ldap(pg.conn, kek, ldap_settings(user_filter="(|(uid={username})(mail={username}))"))
    ldap_on.seed.strategy.remove_entry(dn("avery"))
    ldap_on.person("avery", [ADMINS], mail="avery@acme.example")
    a = auth(pg, kek)
    for i in range(5):  # alternating names: each typed-name key stays under its threshold
        with pytest.raises(AuthError, match="Sign-in failed"):
            a.login("avery" if i % 2 else "avery@acme.example", "wrong-password-1", f"t{i}", "t")
    ldap_on.opened.clear()
    with pytest.raises(AuthError) as e:
        a.login("avery", USER_PW, "203.0.113.34", "t")  # right password, identity locked
    assert (e.value.status, e.value.message) == (401, LOGIN_FAILED)
    assert dn("avery") not in [who for _, who in ldap_on.opened]  # no user bind was tried


def test_padding_holds_no_worker_thread(app, pg, monkeypatch):
    """50 concurrent failed sign-ins wait out their 1 s padding on the event loop, so a
    concurrent request is not queued behind them (the thread pool has about 40 workers)."""
    import asyncio

    import httpx

    from parsemaxxing.auth import passwords, service

    monkeypatch.setattr(service, "_asleep", asyncio.sleep)  # the real wait
    monkeypatch.setattr(service, "_sleep", time.sleep)
    monkeypatch.setattr(passwords, "verify", lambda stored, password: False)  # padding only
    SettingsService(pg.conn, {}).set(AuthSettings, PLATFORM, {"ip_lockout_threshold": 1000}, "test")
    headers = {api.CSRF_HEADER: "1", "Origin": WEB_ORIGIN}

    async def run():
        transport = httpx.ASGITransport(app=app, client=("203.0.113.50", 4000))
        async with httpx.AsyncClient(
            transport=transport, base_url="https://localhost", headers=headers
        ) as c:
            start = time.monotonic()
            logins = [
                asyncio.create_task(
                    c.post("/auth/login", json={"username": f"ghost{i}", "password": "x" * 12})
                )
                for i in range(50)
            ]
            await asyncio.sleep(0.4)  # every sign-in is in its padding by now
            t = time.monotonic()
            health = await c.get("/health")
            took = time.monotonic() - t
            results = await asyncio.gather(*logins)
            return took, health, results, time.monotonic() - start

    took, health, results, total = asyncio.run(run())
    assert health.status_code == 200 and took < 0.2, took
    assert {r.status_code for r in results} == {401} and total >= 1.0
