"""Phase 13 auth (design 7.3), adversarial: route inventory and role matrix, lockout and
backoff, user enumeration (message and timing), session fixation and timeouts, cookie flags,
CSRF with a foreign Origin, API tokens (escalation, expiry, revocation), the setup token, MFA
(required for admins, replay, recovery codes) and a scan for leaked credentials."""

import asyncio
import dataclasses
import ipaddress
import os
import statistics
import time
import uuid
from functools import partial

import psycopg
import pyotp
import pytest
from conftest import TEST_PASSWORD, WEB_ORIGIN, api_client, make_user, settings, sign_in
from fastapi import FastAPI

from parsemaxxing.api import app as api
from parsemaxxing.auth import PUBLIC, SESSION_COOKIE, check_routes, events, passwords
from parsemaxxing.auth.model import Role
from parsemaxxing.auth.policy import route_policies
from parsemaxxing.auth.service import (
    LOGIN_FAILED,
    Auth,
    _key,
    admin_reset,
    issue_setup_token,
    sha256,
)
from parsemaxxing.secrets import Kek
from parsemaxxing.settings import AuthSettings

NEW_PASSWORD = "another-synthetic-pass-9b2d"  # noqa: S105  # gitleaks:allow


@pytest.fixture
def app(pg, pg_dsn, tmp_path):
    s = dataclasses.replace(settings(tmp_path), runs_dir=tmp_path / "runs")
    pg.conn.execute("DELETE FROM settings_groups WHERE grp = 'auth'")  # defaults: MFA required
    return api.create_app(s, dsn=pg_dsn, migrate=True, kek=Kek(os.urandom(32)))


@pytest.fixture
def client(app):
    with api_client(app) as c:
        yield c


def login(client, username, password=TEST_PASSWORD):
    return client.post("/auth/login", json={"username": username, "password": password})


def enrol(client, body=None):
    """Enrol MFA on the client's session; returns (totp, recovery codes). A full session
    re-enters the password (the default body); a session in stage "enrol" may send none."""
    r = client.post("/auth/mfa/enrol", json=body or {"password": TEST_PASSWORD})
    assert r.status_code == 200, r.text
    secret = r.json()["secret"]
    totp = pyotp.TOTP(secret)
    r = client.post("/auth/mfa/confirm", json={"code": totp.now()})
    assert r.status_code == 200, r.text
    return totp, r.json()["recovery_codes"]


def _next_step_code(totp: pyotp.TOTP) -> str:
    """A code for the next time step (accepted within the ±1 window, never used before)."""
    return totp.at(time.time() + totp.interval)


# --- route policy registry -------------------------------------------------------------------


def test_every_route_has_a_policy(app):
    table = route_policies(app)
    assert {k for k, v in table.items() if v is None} == set(PUBLIC)
    assert len(table) > 30


def test_a_route_without_a_policy_stops_the_build(app):
    @app.get("/runs-export")
    def leak() -> dict:
        return {}

    with pytest.raises(RuntimeError, match="GET /runs-export: no route policy"):
        check_routes(app)


def test_a_public_route_cannot_also_carry_a_policy():
    from fastapi import Depends

    from parsemaxxing.auth.policy import VIEWER

    def bare(with_policy: bool) -> FastAPI:
        app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
        for method, path in sorted(PUBLIC):
            deps = [Depends(VIEWER)] if with_policy and path == "/health" else []
            app.add_api_route(path, lambda: {}, methods=[method], dependencies=deps)
        return app

    check_routes(bare(False))
    with pytest.raises(RuntimeError, match="GET /health: public and also has a role policy"):
        check_routes(bare(True))


def _path(path: str) -> str:
    return (
        path.replace("{job}", "abcd1234")
        .replace("{user_id}", str(uuid.uuid4()))
        .replace("{token_id}", str(uuid.uuid4()))
        .replace("{session_id}", str(uuid.uuid4()))
        .replace("{app_name}", "TA-parsemaxxing-acme-firewall")
    )


@pytest.mark.parametrize("who", ["anonymous", "viewer", "admin"])
def test_every_route_as_anonymous_viewer_and_admin(app, pg, who):
    """BFLA: each route answers each role as its policy says (a fresh session per call)."""
    auth = Auth(pg.conn, AuthSettings())
    user = make_user(pg.conn, f"matrix-{who}", "viewer" if who == "viewer" else "admin")
    wrong = []
    for (method, path), pol in sorted(route_policies(app).items()):
        with api_client(app) as c:
            if who != "anonymous":
                c.cookies.set(SESSION_COOKIE, auth.new_session(user["id"], "full", "t", "t"))
            status = c.request(method, _path(path)).status_code
        if pol is None:
            ok = status not in (401, 403)
        elif who == "anonymous":
            ok = status == 401
        elif "full" not in pol.stages:  # the MFA step only takes a pending session
            ok = status in (401, 403)
        elif who == "viewer" and pol.role == Role.ADMIN:
            ok = status == 403
        else:
            ok = status not in (401, 403)
        if not ok:
            wrong.append(f"{method} {path}: {status}")
    assert not wrong, wrong


def test_anonymous_is_refused_before_the_body_is_read(client):
    r = client.post("/uploads", content=b"x" * 1000, headers={"Content-Length": "1000"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthorized"


# --- login, enumeration, lockout -------------------------------------------------------------


def test_unknown_user_and_wrong_password_look_the_same(client, pg):
    make_user(pg.conn, "alice", "viewer")
    a, b = login(client, "alice", "wrong-password-xyz-1"), login(client, "nobody-here")
    assert a.status_code == b.status_code == 401
    assert a.json()["error"]["message"] == b.json()["error"]["message"] == LOGIN_FAILED
    assert SESSION_COOKIE not in a.headers.get("set-cookie", "")


def test_unknown_user_and_wrong_password_take_the_same_time(pg):
    """Same timing class: the unknown user gets a dummy Argon2 verify."""
    auth = Auth(pg.conn, AuthSettings(ip_lockout_threshold=1000, lockout_threshold=20))
    make_user(pg.conn, "timed", "viewer")
    passwords.verify(None, "warm-up")

    def took(name: str) -> float:
        start = time.perf_counter()
        with pytest.raises(Exception, match="Sign-in failed"):
            auth.login(name, "wrong-password-xyz-1", "192.0.2.9", "t")
        return time.perf_counter() - start

    known = statistics.median(took("timed") for _ in range(5))
    unknown = statistics.median(took(f"ghost{i}") for i in range(5))
    assert 0.6 < known / unknown < 1.6, (known, unknown)


def test_a_disabled_account_fails_like_a_wrong_password(client, pg):
    user = make_user(pg.conn, "gone", "viewer")
    pg.conn.execute("UPDATE users SET disabled_at = now() WHERE id = %s", (user["id"],))
    r = login(client, "gone")
    assert r.status_code == 401 and r.json()["error"]["message"] == LOGIN_FAILED


def test_lockout_after_repeated_failures_even_with_the_right_password(client, pg):
    make_user(pg.conn, "bob", "viewer")
    for _ in range(5):
        assert login(client, "bob", "wrong-password-xyz-1").status_code == 401
    r = login(client, "bob")
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0
    assert "Too many attempts" in r.json()["error"]["message"]
    rows = events.recent(pg.conn, event="lockout")
    assert rows and rows[0]["actor"] == "bob"


def test_unknown_user_names_lock_too(client):
    for _ in range(5):
        login(client, "nobody-at-all")
    assert login(client, "nobody-at-all").status_code == 429


def test_per_ip_lockout_across_user_names(client, pg):
    make_user(pg.conn, "carol", "viewer")
    for i in range(20):
        login(client, f"spray{i}")
    assert login(client, "carol").status_code == 429


def test_backoff_doubles_and_is_capped(pg):
    auth = Auth(pg.conn, AuthSettings(lockout_base_seconds=60, lockout_max_seconds=900))
    waits = [auth.fail(sha256("k"), 5) for _ in range(10)]
    assert waits == [0, 0, 0, 0, 60, 120, 240, 480, 900, 900]


# --- sessions --------------------------------------------------------------------------------


def test_login_sets_a_hardened_cookie(client, pg):
    make_user(pg.conn, "dave", "viewer")
    r = login(client, "dave")
    assert r.status_code == 200 and r.json()["stage"] == "full"
    cookie = r.headers["set-cookie"]
    assert cookie.startswith(f"{SESSION_COOKIE}=")
    for flag in ("HttpOnly", "Secure", "SameSite=strict", "Path=/"):
        assert flag.lower() in cookie.lower()
    assert "domain=" not in cookie.lower()
    raw = client.cookies[SESSION_COOKIE]
    stored = pg.conn.execute("SELECT token_hash FROM sessions").fetchone()["token_hash"]
    assert stored == sha256(raw) and raw not in stored  # only the hash is stored


def test_session_fixation_the_id_rotates_at_login(client, pg):
    make_user(pg.conn, "erin", "viewer")
    login(client, "erin")
    before = client.cookies[SESSION_COOKIE]
    login(client, "erin")
    after = client.cookies[SESSION_COOKIE]
    assert before != after
    with api_client(client.app) as old:
        old.cookies.set(SESSION_COOKIE, before)
        assert old.get("/runs").status_code == 401  # the earlier session ended
    with api_client(client.app) as planted:  # an attacker-chosen id is never adopted
        planted.cookies.set(SESSION_COOKIE, "attacker-chosen-value")
        r = login(planted, "erin")
        assert r.status_code == 200
        assert r.headers["set-cookie"].startswith(f"{SESSION_COOKIE}=")
        assert "attacker-chosen-value" not in r.headers["set-cookie"]


@pytest.mark.parametrize(
    "change",
    [
        "UPDATE sessions SET last_seen_at = now() - interval '31 minutes'",  # idle
        "UPDATE sessions SET expires_at = now() - interval '1 second'",  # absolute
        "UPDATE sessions SET revoked_at = now()",
    ],
    ids=["idle", "absolute", "revoked"],
)
def test_expired_and_revoked_sessions_are_refused(client, pg, change):
    sign_in(client, pg.conn, "frank", "viewer")
    assert client.get("/runs").status_code == 200
    pg.conn.execute(change)
    r = client.get("/runs")
    assert r.status_code == 401 and "session ended" in r.json()["error"]["message"]


def test_logout_revokes_and_clears(client, pg):
    make_user(pg.conn, "gina", "viewer")
    login(client, "gina")
    raw = client.cookies[SESSION_COOKIE]
    r = client.post("/auth/logout")
    assert r.status_code == 200 and "max-age=0" in r.headers["set-cookie"].lower()
    with api_client(client.app) as c:
        c.cookies.set(SESSION_COOKIE, raw)
        assert c.get("/runs").status_code == 401


def test_password_change_revokes_every_other_session(client, pg, app):
    make_user(pg.conn, "hank", "viewer")
    login(client, "hank")
    raw = client.post("/auth/tokens", json={"name": "t", "role": "viewer"}).json()["token"]
    with api_client(app) as other:
        login(other, "hank")
        r = client.post(
            "/auth/password",
            json={"current_password": TEST_PASSWORD, "new_password": NEW_PASSWORD},
        )
        assert r.status_code == 200, r.text
        assert other.get("/runs").status_code == 401
    with _bearer(app, raw) as cli:  # API tokens end with the password (M3)
        assert cli.get("/runs").status_code == 401
    assert client.get("/runs").status_code == 200  # this one got a fresh session
    assert login(client, "hank", NEW_PASSWORD).status_code == 200


@pytest.mark.parametrize(
    "password", ["short-pass", "passwordpassword", "Password1234", "hank-is-my-name-1"]
)
def test_password_rule(client, pg, password):
    make_user(pg.conn, "hank", "viewer")
    login(client, "hank")
    r = client.post(
        "/auth/password", json={"current_password": TEST_PASSWORD, "new_password": password}
    )
    assert r.status_code == 422


def test_role_change_signs_the_user_out_and_keeps_an_admin(client, pg, app):
    me = sign_in(client, pg.conn, "root1")
    other = make_user(pg.conn, "ivy", "viewer")
    with api_client(app) as ivy:
        sign_in_existing(ivy, pg, other)
        raw = ivy.post("/auth/tokens", json={"name": "t", "role": "viewer"}).json()["token"]
        assert (
            client.post(f"/auth/users/{other['id']}/role", json={"role": "admin"}).json()["role"]
            == "admin"
        )
        assert ivy.get("/runs").status_code == 401
    with _bearer(app, raw) as cli:  # tokens end with a role change (M3)
        assert cli.get("/runs").status_code == 401
    # The last active admin cannot be demoted or disabled.
    pg.conn.execute("UPDATE users SET role = 'viewer' WHERE id = %s", (other["id"],))
    assert client.post(f"/auth/users/{me['id']}/role", json={"role": "viewer"}).status_code == 409
    assert client.post(f"/auth/users/{me['id']}/disable").status_code == 409


def sign_in_existing(client, pg, user):
    raw = Auth(pg.conn, AuthSettings()).new_session(user["id"], "full", "t", "t")
    client.cookies.set(SESSION_COOKIE, raw)


def test_a_session_of_another_user_cannot_be_revoked(client, pg, app):
    sign_in(client, pg.conn, "jack", "viewer")
    with api_client(app) as other:
        sign_in(other, pg.conn, "kate", "viewer")
        (theirs,) = other.get("/auth/sessions").json()
    assert client.post(f"/auth/sessions/{theirs['id']}/revoke").status_code == 404


# --- CSRF ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "https://evil.example.com"},
        {"Origin": ""},  # a cookie without an Origin
        {api.CSRF_HEADER: ""},
    ],
    ids=["foreign-origin", "no-origin", "no-header"],
)
def test_csrf_is_refused_with_a_session(client, pg, headers):
    sign_in(client, pg.conn, "admin2")
    h = {api.CSRF_HEADER: "1", "Origin": WEB_ORIGIN} | headers
    h = {k: v for k, v in h.items() if not (k == "Origin" and v == "")}
    with api_client(client.app) as c:
        c.headers.clear()
        c.cookies.update(client.cookies)
        r = c.post("/admin/kill", json={"on": True}, headers=h)
    assert r.status_code == 403
    assert client.get("/admin/status").json()["kill_switch"] is False


# --- API tokens ------------------------------------------------------------------------------


def _bearer(app, raw):
    c = api_client(app)
    c.headers.pop("origin")  # the CLI sends no Origin and no cookie
    c.headers["Authorization"] = f"Bearer {raw}"
    return c


def test_tokens_role_scoped_shown_once_and_hashed(client, pg, app):
    sign_in(client, pg.conn, "lee", "viewer")
    r = client.post("/auth/tokens", json={"name": "ci", "role": "viewer", "expires_in_days": 7})
    assert r.status_code == 201
    raw = r.json()["token"]
    assert raw.startswith("pmxt_") and len(raw) == 48
    assert raw not in client.get("/auth/tokens").text
    assert pg.conn.execute("SELECT token_hash FROM api_tokens").fetchone()["token_hash"] == sha256(
        raw
    )
    with _bearer(app, raw) as cli:
        assert cli.get("/runs").status_code == 200
        assert cli.post("/admin/kill", json={"on": True}).status_code == 403
        # A token cannot mint tokens (session only) nor manage the account.
        assert cli.post("/auth/tokens", json={"name": "x", "role": "viewer"}).status_code == 403
        assert cli.get("/auth/sessions").status_code == 403


def test_role_escalation_through_token_creation_is_refused(client, pg):
    sign_in(client, pg.conn, "mia", "viewer")
    r = client.post("/auth/tokens", json={"name": "up", "role": "admin", "expires_in_days": 7})
    assert r.status_code == 403
    assert pg.conn.execute("SELECT count(*) AS n FROM api_tokens").fetchone()["n"] == 0
    over = client.post("/auth/tokens", json={"name": "x", "role": "viewer", "expires_in_days": 91})
    assert over.status_code == 422


def test_a_demoted_owner_demotes_their_tokens(client, pg, app):
    user = sign_in(client, pg.conn, "ned")
    raw = client.post("/auth/tokens", json={"name": "a", "role": "admin"}).json()["token"]
    make_user(pg.conn, "other-admin")
    pg.conn.execute("UPDATE users SET role = 'viewer' WHERE id = %s", (user["id"],))
    with _bearer(app, raw) as cli:
        assert cli.post("/admin/kill", json={"on": True}).status_code == 403


@pytest.mark.parametrize(
    "change",
    [
        "UPDATE api_tokens SET revoked_at = now()",
        "UPDATE api_tokens SET created_at = now() - interval '10 days',"
        " expires_at = now() - interval '1 second'",
        "UPDATE users SET disabled_at = now()",
    ],
    ids=["revoked", "expired", "owner-disabled"],
)
def test_expired_and_revoked_tokens_are_refused(client, pg, app, change):
    sign_in(client, pg.conn, "olga", "viewer")
    raw = client.post("/auth/tokens", json={"name": "t", "role": "viewer"}).json()["token"]
    pg.conn.execute(change)
    with _bearer(app, raw) as cli:
        r = cli.get("/runs")
    assert r.status_code == 401


def test_revoke_through_the_api_and_bad_tokens_are_throttled(client, pg, app):
    sign_in(client, pg.conn, "pat", "viewer")
    made = client.post("/auth/tokens", json={"name": "t", "role": "viewer"}).json()
    assert client.post(f"/auth/tokens/{made['id']}/revoke").status_code == 200
    with _bearer(app, made["token"]) as cli:
        assert cli.get("/runs").status_code == 401
    with _bearer(app, "pmxt_" + "A" * 43) as cli:
        codes = [cli.get("/runs").status_code for _ in range(21)]
    assert codes[0] == 401 and codes[-1] == 429


def test_another_users_token_cannot_be_revoked_by_a_viewer(client, pg, app):
    sign_in(client, pg.conn, "quin", "viewer")
    with api_client(app) as other:
        sign_in(other, pg.conn, "rita", "viewer")
        theirs = other.post("/auth/tokens", json={"name": "t", "role": "viewer"}).json()
    assert client.post(f"/auth/tokens/{theirs['id']}/revoke").status_code == 404


# --- first-run setup token -------------------------------------------------------------------


def _setup(client, token, username="first"):
    body = {"token": token, "username": username, "password": TEST_PASSWORD}
    return client.post("/setup", json=body)


def test_setup_token_is_single_use(client, app):
    path = app.state.setup_token_path
    token = path.read_text().strip()
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    assert client.get("/setup").json() == {"needed": True}
    assert _setup(client, "x" * 43).status_code == 403
    r = _setup(client, token)
    assert r.status_code == 201 and r.json()["stage"] == "enrol"  # MFA required for admins
    assert r.json()["user"]["role"] == "admin" and not path.exists()
    with api_client(app) as again:
        assert _setup(again, token, "second").status_code == 409
    assert client.get("/setup").json() == {"needed": False}


def test_an_expired_setup_token_is_refused(client, app, pg):
    token = app.state.setup_token_path.read_text().strip()
    pg.conn.execute("UPDATE setup_token SET expires_at = now() - interval '1 second'")
    r = _setup(client, token)
    assert r.status_code == 403 and "not valid" in r.json()["error"]["message"]


def test_no_setup_token_once_an_admin_exists(pg, pg_dsn, tmp_path):
    make_user(pg.conn, "boss")
    s = dataclasses.replace(settings(tmp_path), runs_dir=tmp_path / "runs")
    app = api.create_app(s, dsn=pg_dsn)
    assert not app.state.setup_token_path.exists()


# --- MFA -------------------------------------------------------------------------------------


def test_mfa_is_required_for_admins_and_replay_is_refused(client, pg, app):
    make_user(pg.conn, "sam")
    assert login(client, "sam").json()["stage"] == "enrol"
    assert client.get("/runs").status_code == 403  # nothing else until MFA is set up
    r = client.post("/auth/mfa/enrol")  # stage "enrol": the password was just entered
    assert r.status_code == 200
    totp = pyotp.TOTP(r.json()["secret"])
    assert client.post("/auth/mfa/confirm", json={"code": totp.now()}).status_code == 200
    assert client.get("/runs").status_code == 200
    with api_client(app) as c:
        assert login(c, "sam").json()["stage"] == "mfa"
        assert c.get("/runs").status_code == 401
        assert c.post("/auth/login/mfa", json={"code": "000000"}).status_code == 401
        code = _next_step_code(totp)
        assert c.post("/auth/login/mfa", json={"code": code}).status_code == 200
        assert c.get("/runs").status_code == 200
    with api_client(app) as replay:
        login(replay, "sam")
        assert replay.post("/auth/login/mfa", json={"code": code}).status_code == 401
    # MFA cannot be turned off while it is required for admins.
    r = client.post("/auth/mfa/disable", json={"password": TEST_PASSWORD})
    assert r.status_code == 409


def test_mfa_requirement_can_be_turned_off(client, pg):
    from parsemaxxing.settings import PLATFORM, SettingsService

    SettingsService(pg.conn, {}).set(AuthSettings, PLATFORM, {"require_mfa_admins": False}, "t")
    make_user(pg.conn, "tom")
    assert login(client, "tom").json()["stage"] == "full"


def test_recovery_codes_are_single_use_and_hashed(client, pg, app):
    make_user(pg.conn, "uma", "viewer")
    login(client, "uma")
    _, codes = enrol(client)
    assert len(codes) == 10 and len(set(codes)) == 10
    stored = {r["code_hash"] for r in pg.conn.execute("SELECT code_hash FROM recovery_codes")}
    assert not any(c in h for c in codes for h in stored)
    with api_client(app) as c:
        login(c, "uma")
        r = c.post("/auth/login/mfa", json={"recovery_code": codes[0].upper()})
        assert r.status_code == 200 and r.json()["recovery_codes_left"] == 9
    with api_client(app) as c:
        login(c, "uma")
        assert c.post("/auth/login/mfa", json={"recovery_code": codes[0]}).status_code == 401


def test_mfa_failures_lock(client, pg):
    make_user(pg.conn, "vic", "viewer")
    login(client, "vic")
    enrol(client)
    login(client, "vic")
    for _ in range(5):
        client.post("/auth/login/mfa", json={"code": "000000"})
    assert client.post("/auth/login/mfa", json={"code": "000000"}).status_code == 429


def test_the_totp_secret_is_in_the_vault_only(client, pg):
    make_user(pg.conn, "wes", "viewer")
    login(client, "wes")
    secret = client.post("/auth/mfa/enrol", json={"password": TEST_PASSWORD}).json()["secret"]
    row = pg.conn.execute("SELECT ciphertext FROM secrets").fetchone()
    assert secret.encode() not in bytes(row["ciphertext"])
    assert secret not in str(pg.conn.execute("SELECT * FROM user_mfa").fetchall())


# --- audit, break-glass, leaks ---------------------------------------------------------------


def test_auth_events_are_append_only_and_chained(client, pg):
    make_user(pg.conn, "xena", "viewer")
    login(client, "xena")
    login(client, "xena", "wrong-password-xyz-1")
    assert events.verify(pg.conn)["problems"] == []
    with pytest.raises(psycopg.errors.RaiseException), pg.conn.transaction():
        pg.conn.execute("UPDATE auth_events SET outcome = 'success'")
    got = [(e["event"], e["outcome"]) for e in client.get("/audit").json()]
    assert ("login", "failure") in got and ("login", "success") in got


def test_admin_reset_is_break_glass(client, pg, app):
    user = make_user(pg.conn, "yuri")
    login(client, "yuri")
    enrol(client)
    raw = client.post("/auth/tokens", json={"name": "t", "role": "admin"}).json()["token"]
    mfa_key = _key("mfa", str(user["id"]))
    Auth(pg.conn, AuthSettings()).fail(mfa_key, 1)  # a locked MFA step
    for _ in range(6):
        login(client, "yuri", "wrong-password-xyz-1")
    admin_reset(pg.conn, "yuri", NEW_PASSWORD)
    with _bearer(app, raw) as cli:  # API tokens revoked with the sessions (M3)
        assert cli.get("/runs").status_code == 401
    left = pg.conn.execute("SELECT count(*) AS n FROM auth_throttle WHERE key = %s", (mfa_key,))
    assert left.fetchone()["n"] == 0
    with api_client(app) as c:
        assert login(c, "yuri", NEW_PASSWORD).json()["stage"] == "enrol"  # MFA cleared
    assert client.get("/runs").status_code == 401  # earlier sessions revoked
    reset = events.recent(pg.conn, event="admin_reset")[0]
    assert reset["actor"] == "cli:admin-reset" and reset["detail"]["tokens_revoked"] == 1


def test_no_credential_reaches_a_response_log_or_audit_row(client, pg, app, caplog):
    caplog.set_level("DEBUG")
    seen: list[str] = []
    make_user(pg.conn, "zoe")
    for r in (login(client, "zoe"), login(client, "zoe", NEW_PASSWORD)):
        seen.append(r.text + str(r.headers.get("set-cookie", "")))
    login(client, "zoe")
    session = client.cookies[SESSION_COOKIE]
    enrolled = client.post("/auth/mfa/enrol").json()
    totp = pyotp.TOTP(enrolled["secret"])
    confirmed = client.post("/auth/mfa/confirm", json={"code": totp.now()}).json()
    token = client.post("/auth/tokens", json={"name": "t", "role": "viewer"}).json()["token"]
    for path in ("/auth/me", "/auth/sessions", "/auth/tokens", "/auth/users", "/audit"):
        seen.append(client.get(path).text)
    audit = str(pg.conn.execute("SELECT * FROM auth_events").fetchall())
    secrets = [TEST_PASSWORD, NEW_PASSWORD, session, enrolled["secret"], token,
               *confirmed["recovery_codes"]]  # fmt: skip
    for value in secrets:
        assert value not in audit and value not in caplog.text
        assert not any(value in text for text in seen)


# --- CLI -------------------------------------------------------------------------------------


def test_cli_setup_token_admin_reset_and_verify(pg, pg_dsn, tmp_path, monkeypatch, capsys):
    from parsemaxxing.cli import main as cli_main

    monkeypatch.setenv("DATABASE_URL", pg_dsn)
    monkeypatch.setenv("MIGRATE_DATABASE_URL", pg_dsn)
    monkeypatch.setenv("PARSEMAXXING_RUNS_DIR", str(tmp_path / "runs"))
    base = ["--env-file", str(tmp_path / "none.env")]
    assert cli_main([*base, "setup-token"]) == 0
    token = capsys.readouterr().out.splitlines()[-1]
    assert (tmp_path / "runs" / "setup-token").read_text().strip() == token
    assert pg.conn.execute("SELECT token_hash FROM setup_token").fetchone()["token_hash"] == sha256(
        token
    )
    make_user(pg.conn, "root9")
    assert cli_main([*base, "setup-token"]) == 4  # setup is complete

    answers = iter([NEW_PASSWORD, NEW_PASSWORD])
    monkeypatch.setattr("getpass.getpass", lambda prompt="": next(answers))
    assert cli_main([*base, "admin", "reset", "root9"]) == 0
    out = capsys.readouterr().out
    assert NEW_PASSWORD not in out and "sessions revoked" in out
    answers = iter([NEW_PASSWORD, NEW_PASSWORD])
    assert cli_main([*base, "admin", "reset", "nobody"]) == 4
    assert cli_main([*base, "ledger", "verify"]) == 0
    assert "auth_events:" in capsys.readouterr().out


def test_the_app_role_cannot_rewrite_credentials_or_the_audit(pg):
    conn = pg.conn
    conn.execute("SET ROLE parsemaxxing_app")
    try:
        events.record(conn, "grant_check", "success", "test")
        for sql in (
            "UPDATE sessions SET stage = 'full'",
            "UPDATE sessions SET token_hash = token_hash",
            "UPDATE api_tokens SET role = 'admin'",
            "UPDATE users SET username = username",
            "DELETE FROM auth_events",
            "DELETE FROM users",
            "TRUNCATE auth_events",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
                conn.execute(sql)
    finally:
        conn.execute("RESET ROLE")


# --- appsec Phase 13 findings ----------------------------------------------------------------

ORIGINS = (
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "https://pmx.example.com",
    "https://pmx.example.com:8443",
)


def test_every_listed_web_origin_works_and_a_foreign_one_is_refused(
    pg, pg_dsn, tmp_path, monkeypatch
):
    """M2: the web is reached through several origins; each signs in and changes state."""
    monkeypatch.setenv("WEB_ORIGINS", ",".join(ORIGINS))
    s = dataclasses.replace(settings(tmp_path), runs_dir=tmp_path / "runs")
    app = api.create_app(s, dsn=pg_dsn, migrate=True, kek=Kek(os.urandom(32)))
    make_user(pg.conn, "multi", "viewer")
    for origin in (*ORIGINS, "https://evil.example.com"):
        with api_client(app) as c:
            c.headers["Origin"] = origin
            pre = c.options(
                "/auth/login",
                headers={"Access-Control-Request-Method": "POST", "Origin": origin},
            )
            r = login(c, "multi")
            if origin.startswith("https://evil"):
                assert r.status_code == 403 and "access-control-allow-origin" not in pre.headers
                continue
            assert pre.headers["access-control-allow-origin"] == origin
            assert r.status_code == 200, (origin, r.text)
            made = c.post("/auth/tokens", json={"name": "t", "role": "viewer"})
            assert made.status_code == 201, (origin, made.text)


def test_mfa_enrol_on_a_signed_in_session_needs_the_password(client, pg):
    """L1: a stolen full session cannot swap in the attacker's authenticator."""
    make_user(pg.conn, "enrol1", "viewer")
    assert login(client, "enrol1").json()["stage"] == "full"
    assert client.post("/auth/mfa/enrol").status_code == 422
    assert client.post("/auth/mfa/enrol", json={}).status_code == 422
    wrong = client.post("/auth/mfa/enrol", json={"password": "wrong-password-xyz-1"})
    assert wrong.status_code == 403
    assert client.post("/auth/mfa/enrol", json={"password": "x", "extra": 1}).status_code == 422
    assert pg.conn.execute("SELECT count(*) AS n FROM user_mfa").fetchone()["n"] == 0
    enrol(client)  # with the right password
    assert pg.conn.execute("SELECT count(*) AS n FROM user_mfa").fetchone()["n"] == 1


def test_me_says_whether_mfa_is_required(client, pg, app):
    from parsemaxxing.settings import PLATFORM, SettingsService

    sign_in(client, pg.conn, "boss1")
    assert client.get("/auth/me").json()["mfa_required"] is True
    with api_client(app) as v:
        sign_in(v, pg.conn, "watch1", "viewer")
        assert v.get("/auth/me").json()["mfa_required"] is False
    SettingsService(pg.conn, {}).set(AuthSettings, PLATFORM, {"require_mfa_admins": False}, "t")
    assert client.get("/auth/me").json()["mfa_required"] is False


def test_disable_revokes_the_users_tokens(client, pg, app):
    sign_in(client, pg.conn, "root2")
    with api_client(app) as v:
        user = sign_in(v, pg.conn, "leaver", "viewer")
        v.post("/auth/tokens", json={"name": "t", "role": "viewer"})
    assert client.post(f"/auth/users/{user['id']}/disable").status_code == 200
    client.post(f"/auth/users/{user['id']}/enable")
    revoked = pg.conn.execute("SELECT revoked_at FROM api_tokens WHERE user_id = %s", (user["id"],))
    assert revoked.fetchone()["revoked_at"] is not None  # re-enabling does not bring it back


def _stream_request(app, cookie: str = "", bearer: str = ""):
    from starlette.requests import Request

    headers = [(b"host", b"localhost")]
    if cookie:
        headers.append((b"cookie", f"{SESSION_COOKIE}={cookie}".encode()))
    if bearer:
        headers.append((b"authorization", f"Bearer {bearer}".encode()))

    async def receive():  # an open connection: never a disconnect
        await asyncio.sleep(3600)

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/runs/x/stream",
        "headers": headers,
        "query_string": b"",
        "client": ("192.0.2.10", 40000),
        "app": app,
    }
    return Request(scope, receive)


def _stream_until_closed(pg, pg_dsn, request, cut, seconds: float = 6.0):
    """Run the event stream; `cut()` runs after the first chunk. True when the stream closed
    by itself."""
    pg.enqueue("sse00002", "sse:2", "f" * 64, "/tmp/x", {})

    async def go():
        gen = api._sse(pg_dsn, "sse00002", 0, request, partial(api._still_viewer, request))
        first = True
        async for _ in gen:
            if first:
                await asyncio.get_running_loop().run_in_executor(None, cut)
                first = False
        return True

    try:
        return asyncio.run(asyncio.wait_for(go(), timeout=seconds))
    except TimeoutError:
        return False


@pytest.mark.parametrize("credential", ["session", "token"])
def test_an_open_event_stream_closes_once_its_credential_is_revoked(
    pg, pg_dsn, app, monkeypatch, credential
):
    """L2: a stream opened before a revocation does not keep delivering events."""
    monkeypatch.setattr(api, "RECHECK_S", 0)
    auth = Auth(pg.conn, AuthSettings())
    user = make_user(pg.conn, f"streamer-{credential}", "viewer")
    if credential == "session":
        raw = auth.new_session(user["id"], "full", "t", "t")
        request = _stream_request(app, cookie=raw)
        cut = lambda: auth.revoke_all(user["id"], "test")  # noqa: E731
    else:
        who = auth.session(auth.new_session(user["id"], "full", "t", "t"))
        raw, _ = auth.create_token(who, "t", Role.VIEWER, 7, "t")
        request = _stream_request(app, bearer=raw)
        cut = lambda: pg.conn.execute("UPDATE api_tokens SET revoked_at = now()")  # noqa: E731
    assert _stream_until_closed(pg, pg_dsn, request, cut)


def test_an_open_event_stream_stays_while_valid_and_is_not_activity(pg, pg_dsn, app, monkeypatch):
    monkeypatch.setattr(api, "RECHECK_S", 0)
    auth = Auth(pg.conn, AuthSettings())
    user = make_user(pg.conn, "streamer-ok", "viewer")
    raw = auth.new_session(user["id"], "full", "t", "t")
    pg.conn.execute("UPDATE sessions SET last_seen_at = now() - interval '5 minutes'")
    before = pg.conn.execute("SELECT last_seen_at FROM sessions").fetchone()["last_seen_at"]
    assert not _stream_until_closed(pg, pg_dsn, _stream_request(app, cookie=raw), lambda: None, 3)
    after = pg.conn.execute("SELECT last_seen_at FROM sessions").fetchone()["last_seen_at"]
    assert after == before  # the re-check does not hold the idle timeout off


def test_engine_workers_share_one_setup_token(pg, pg_dsn, tmp_path):
    """The engine runs several uvicorn workers; each builds the app and must not replace the
    token another worker just wrote."""
    s = dataclasses.replace(settings(tmp_path), runs_dir=tmp_path / "runs")
    apps = [api.create_app(s, dsn=pg_dsn, migrate=i == 0) for i in range(4)]
    path = apps[0].state.setup_token_path
    token = path.read_text().strip()
    stored = pg.conn.execute("SELECT token_hash FROM setup_token").fetchone()["token_hash"]
    assert stored == sha256(token)
    issued = events.recent(pg.conn, event="setup_token_issued")
    assert len(issued) == 1
    with api_client(apps[-1]) as c:
        assert _setup(c, token).status_code == 201


def test_concurrent_setup_token_issue_agrees(pg, pg_dsn, tmp_path):
    import threading

    from parsemaxxing.ledger import store as db

    path = tmp_path / "setup-token"
    got: list[str | None] = []

    def worker():
        with db.connect(pg_dsn) as conn:
            got.append(issue_setup_token(conn, path))

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(set(got)) == 1 and got[0] == path.read_text().strip()
    assert len(events.recent(pg.conn, event="setup_token_issued")) == 1


@pytest.mark.parametrize(
    "change",
    [
        "UPDATE setup_token SET expires_at = now() - interval '1 second'",
        "UPDATE setup_token SET used_at = now()",
        "missing-file",
        "UPDATE setup_token SET token_hash = repeat('0', 64)",  # the file is not the token
    ],
    ids=["expired", "used", "missing-file", "mismatch"],
)
def test_a_stale_setup_token_is_replaced(pg, tmp_path, change):
    path = tmp_path / "setup-token"
    first = issue_setup_token(pg.conn, path)
    if change == "missing-file":
        path.unlink()
    else:
        pg.conn.execute(change)
    second = issue_setup_token(pg.conn, path)
    assert second and second != first and path.read_text().strip() == second
    assert pg.conn.execute("SELECT token_hash FROM setup_token").fetchone()["token_hash"] == sha256(
        second
    )


def test_force_reissues_the_setup_token(pg, tmp_path):
    path = tmp_path / "setup-token"
    first = issue_setup_token(pg.conn, path)
    assert issue_setup_token(pg.conn, path) == first
    second = issue_setup_token(pg.conn, path, force=True)
    assert second != first and path.read_text().strip() == second
    assert issue_setup_token(pg.conn, path) == second


def _ip_request(peer: str, forwarded: str, trusted: list[str]):
    from types import SimpleNamespace

    nets = [ipaddress.ip_network(n) for n in trusted]
    return SimpleNamespace(
        client=SimpleNamespace(host=peer),
        headers={"x-forwarded-for": forwarded} if forwarded else {},
        app=SimpleNamespace(state=SimpleNamespace(trusted_proxies=nets)),
    )


@pytest.mark.parametrize(
    "peer, forwarded, trusted, expected",
    [
        ("203.0.113.5", "198.51.100.7", [], "203.0.113.5"),  # no proxy trusted
        ("203.0.113.5", "198.51.100.7", ["192.0.2.0/24"], "203.0.113.5"),  # untrusted peer
        ("192.0.2.2", "198.51.100.7", ["192.0.2.0/24"], "198.51.100.7"),  # the web proxy
        ("192.0.2.2", "203.0.113.9, 198.51.100.7", ["192.0.2.0/24"], "198.51.100.7"),  # last hop
        ("192.0.2.2", "not-an-ip", ["192.0.2.0/24"], "192.0.2.2"),  # garbage: the peer
        ("192.0.2.2", "", ["192.0.2.0/24"], "192.0.2.2"),
    ],
)
def test_x_forwarded_for_only_from_a_trusted_proxy(peer, forwarded, trusted, expected):
    from parsemaxxing.auth.policy import client_ip

    assert client_ip(_ip_request(peer, forwarded, trusted)) == expected
