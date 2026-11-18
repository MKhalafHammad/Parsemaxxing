"""The CLI's mutating commands go through the engine API with an API token (design 7.3, Phase
13): role checks, audit, the error envelope, and the token's handling (file mode, never printed,
never a command-line value). The HTTP transport is a FastAPI TestClient; real PostgreSQL."""

import dataclasses
import os
import re

import pytest
from conftest import FIXTURES, make_user, settings
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from parsemaxxing import cli, config
from parsemaxxing.api import app as api
from parsemaxxing.api.client import Api, ApiError, urlopen_send
from parsemaxxing.auth.model import Principal, Role
from parsemaxxing.auth.service import Auth
from parsemaxxing.orchestrator import promote
from parsemaxxing.secrets import Kek
from parsemaxxing.settings import AuthSettings

URL = "http://127.0.0.1:8080"
SHA = "b" * 64
APP = "TA-parsemaxxing-acme-firewall"
WRONG = "pmxt_" + "x" * 43  # gitleaks:allow


@pytest.fixture
def app(pg, pg_dsn, tmp_path):
    s = dataclasses.replace(settings(tmp_path), runs_dir=tmp_path / "runs")
    return api.create_app(s, dsn=pg_dsn, migrate=True, kek=Kek(os.urandom(32)))


def token(pg, username: str, role: str) -> str:
    user = make_user(pg.conn, username, role)
    who = Principal(str(user["id"]), username, Role(role), "session", "full", "s")
    raw, _ = Auth(pg.conn, AuthSettings()).create_token(who, "cli", Role(role), 30, "t")
    return raw


def transport(app, hook=None):
    """`send` for the CLI: the urllib request replayed into the app, as it would go on the wire
    (no default headers: only what the CLI itself sends)."""
    tc = TestClient(app, base_url=URL)

    def send(request, timeout):
        send.seen.append(request)
        path = request.full_url.removeprefix(URL)
        if hook:
            hook(request.get_method(), path)
        r = tc.request(
            request.get_method(), path, headers=dict(request.header_items()), content=request.data
        )
        return r.status_code, r.content

    send.seen = []
    return send


@pytest.fixture
def run_cli(app, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "POLL_S", 0)
    monkeypatch.delenv("PARSEMAXXING_API_URL", raising=False)

    def go(*argv, hook=None, raw=None):
        if raw is not None:
            monkeypatch.setenv("PARSEMAXXING_API_TOKEN", raw)
        send = transport(app, hook)
        code = cli.main(["--env-file", str(tmp_path / "none.env"), *argv], api_send=send)
        out, err = capsys.readouterr()
        return code, out, err, send.seen

    return go


def awaiting(pg, job: str) -> None:
    pg.conn.execute(
        "UPDATE jobs SET status = 'awaiting_approval', record = %s WHERE id = %s",
        (Jsonb({"sha256_test": SHA, "result": "passed"}), job),
    )


def queued_job(pg, job: str = "cafe0001") -> str:
    pg.enqueue(job, f"k:{job}", job * 8, "/x.log", {})
    return job


def test_run_approve_promote_and_kill_go_through_the_api(pg, run_cli):
    raw = token(pg, "ops1", "admin")

    def worker_did_its_part(method, path):  # stands in for the engine's worker pool
        if method == "GET" and path.startswith("/runs/"):
            job = path.split("/")[2]
            status = pg.get(job)["status"]
            if status == "queued":
                awaiting(pg, job)
            elif status == "approved":
                pg.conn.execute(
                    "UPDATE jobs SET status = 'done', record = record || %s WHERE id = %s",
                    (Jsonb({"smoke": "smoke ok"}), job),
                )

    code, out, err, seen = run_cli(
        "run", str(FIXTURES / "acme_fw.log"), "--vendor", "acme", raw=raw, hook=worker_did_its_part
    )
    assert code == 0, err
    job = re.search(r"job (\w+) queued", out).group(1)
    assert f"approve: parsemaxxing approve {job} --sha256 {SHA}" in out
    row = pg.get(job)
    assert row["created_by"] == "ops1" and row["form"]["auto_approve"] is True
    assert row["form"]["vendor"] == "acme" and row["form"]["validation"] == "uploaded"
    first = seen[0]
    assert first.get_method() == "POST" and first.full_url == f"{URL}/uploads"
    assert first.unredirected_hdrs["Authorization"] == f"Bearer {raw}"  # never on a redirect
    assert first.headers["X-parsemaxxing"] == "1"

    code, out, err, _ = run_cli("approve", job, "--sha256", SHA, raw=raw)
    assert code == 0 and f"approved {SHA}" in out, err
    audit = pg.conn.execute(
        "SELECT actor, detail FROM auth_events WHERE event = 'run_approve'"
    ).fetchone()
    assert audit["actor"] == "ops1" and audit["detail"]["job"] == job
    # Replay: a no-op, not an error.
    assert run_cli("approve", job, "--sha256", SHA, raw=raw)[0] == 0

    code, out, err, _ = run_cli("promote", job, raw=raw, hook=worker_did_its_part)
    assert code == 0 and f"{job}: done smoke ok" in out, err

    code, out, _, _ = run_cli("kill", "on", raw=raw)
    assert code == 0 and "kill switch: on" in out and pg.kill_switch()
    assert run_cli("kill", "off", raw=raw)[0] == 0 and not pg.kill_switch()
    assert (
        pg.conn.execute(
            "SELECT count(*) AS n FROM auth_events WHERE event = 'kill_switch' AND actor = 'ops1'"
        ).fetchone()["n"]
        == 2
    )


def test_reject_and_promote_of_an_unapproved_run(pg, run_cli):
    raw = token(pg, "ops2", "admin")
    job = queued_job(pg)
    code, _, err, _ = run_cli("promote", job, raw=raw)
    assert code == 4 and "not approved" in err
    awaiting(pg, job)
    code, out, _, _ = run_cli("reject", job, raw=raw)
    assert code == 0 and f"{job}: rejected" in out and pg.get(job)["status"] == "rejected"
    code, _, err, _ = run_cli("reject", job, raw=raw)  # replay: a clear refusal
    assert code == 4 and "only a run awaiting approval" in err


def test_a_viewer_token_is_refused_with_the_envelope(pg, run_cli):
    raw = token(pg, "watcher", "viewer")
    awaiting(pg, queued_job(pg))
    code, out, err, _ = run_cli("approve", "cafe0001", "--sha256", SHA, raw=raw)
    assert code == 4 and out == ""
    envelope = r"refused: This needs the admin role\. \(HTTP 403, request [0-9a-f]{32}\)"
    assert re.search(envelope, err)
    assert pg.get("cafe0001")["status"] == "awaiting_approval"
    assert run_cli("kill", "on", raw=raw)[0] == 4 and not pg.kill_switch()


def test_a_wrong_token_is_refused_and_never_printed(pg, run_cli):
    code, out, err, _ = run_cli("kill", "status", raw=WRONG)
    assert code == 4 and "not valid, expired or revoked" in err and "HTTP 401" in err
    assert WRONG not in out + err
    raw = token(pg, "ops3", "admin")
    code, out, err, _ = run_cli("kill", "status", raw=raw)
    assert code == 0 and raw not in out + err


def test_the_token_is_never_a_command_line_value(run_cli):
    with pytest.raises(SystemExit):
        run_cli("kill", "status", "--token", WRONG)


def test_no_token_is_a_clear_refusal(run_cli, monkeypatch):
    monkeypatch.delenv("PARSEMAXXING_API_TOKEN", raising=False)
    code, _, err, seen = run_cli("kill", "status")
    assert code == 4 and "no API token" in err and seen == []


@pytest.mark.parametrize("mode", [0o644, 0o640, 0o604, 0o700])
def test_a_token_file_readable_by_others_is_refused(pg, run_cli, tmp_path, monkeypatch, mode):
    monkeypatch.delenv("PARSEMAXXING_API_TOKEN", raising=False)
    raw = token(pg, "ops4", "admin")
    f = tmp_path / "tok"
    f.write_text(raw + "\n")
    f.chmod(mode)
    code, out, err, seen = run_cli("kill", "status", "--token-file", str(f))
    assert code == 4 and "mode 0600 or 0400" in err and seen == [] and raw not in out + err


@pytest.mark.parametrize("mode", [0o600, 0o400])
def test_a_private_token_file_works_and_wins(pg, run_cli, tmp_path, monkeypatch, mode):
    monkeypatch.setenv("PARSEMAXXING_API_TOKEN", WRONG)
    raw = token(pg, "ops5", "admin")
    f = tmp_path / "tok"
    f.write_text(raw + "\n")
    f.chmod(mode)
    code, out, err, _ = run_cli("kill", "status", "--token-file", str(f))
    assert code == 0 and "kill switch: off" in out, err
    assert raw not in out + err


def test_a_token_file_link_or_garbage_is_refused(pg, run_cli, tmp_path, monkeypatch):
    monkeypatch.delenv("PARSEMAXXING_API_TOKEN", raising=False)
    real = tmp_path / "real"
    real.write_text(token(pg, "ops6", "admin"))
    real.chmod(0o600)
    (tmp_path / "link").symlink_to(real)
    assert run_cli("kill", "status", "--token-file", str(tmp_path / "link"))[0] == 4
    junk = tmp_path / "junk"
    junk.write_text("Bearer x\nX-Injected: 1")
    junk.chmod(0o600)
    code, _, err, seen = run_cli("kill", "status", "--token-file", str(junk))
    assert code == 4 and "not a pmxt_ token" in err and "Injected" not in err and seen == []


def test_queued_runs_take_attempts_from_settings_only(pg, run_cli):
    raw = token(pg, "ops7", "admin")
    code, _, err, seen = run_cli(
        "run", str(FIXTURES / "acme_fw.log"), "--max-attempts", "9", raw=raw
    )
    assert code == 4 and "--max-attempts needs --local" in err and seen == []


def test_a_bad_job_id_never_reaches_the_url(pg, run_cli):
    raw = token(pg, "ops8", "admin")
    code, _, err, seen = run_cli("approve", "../admin/kill", "--sha256", SHA, raw=raw)
    assert code == 4 and "job id" in err and seen == []


@pytest.mark.parametrize(
    ("url", "ok"),
    [
        ("http://127.0.0.1:8080", True),
        ("http://localhost:8080/", True),
        ("http://engine:8080", True),
        ("https://pmx.example.com", True),
        ("http://pmx.example.com:8080", False),  # the token would cross the network in clear
        ("https://user:pw@pmx.example.com", False),
        ("https://pmx.example.com/x?y=1", False),
        ("file:///etc/passwd", False),
        ("ftp://127.0.0.1", False),
    ],
)
def test_api_url(monkeypatch, url, ok):
    monkeypatch.setenv("PARSEMAXXING_API_URL", url)
    if ok:
        assert config.api_url() == url.rstrip("/")
    else:
        with pytest.raises(RuntimeError, match="PARSEMAXXING_API_URL"):
            config.api_url()


def test_an_unreachable_engine_is_a_clear_error():
    with pytest.raises(ApiError, match="cannot reach the engine API") as e:
        Api("http://127.0.0.1:1", WRONG, urlopen_send).call("GET", "/health", timeout=3)
    assert WRONG not in str(e.value)


def test_error_text_from_the_engine_is_printable_only():
    def send(request, timeout):
        return 409, b'{"error": {"message": "bad\\u001b[2Jthing", "request_id": "r1"}}'

    with pytest.raises(ApiError) as e:
        Api(URL, WRONG, send).call("GET", "/x")
    assert str(e.value) == "bad[2Jthing (HTTP 409, request r1)"
    with pytest.raises(ApiError, match="unexpected answer"):
        Api(URL, WRONG, lambda r, t: (502, b"<html>")).call("GET", "/x")


# --- rollback (route and CLI) -------------------------------------------------------------------


def registered(pg) -> None:
    owner = queued_job(pg, "beef0001")
    record = {"job": owner, "app": APP, "sourcetype": "acme:fw", "vendor": "acme"}
    pg.register_ta({**record, "product": "firewall"}, "1.0.0", "a" * 64)


@pytest.fixture
def fake_rollback(monkeypatch):
    calls = []

    def rollback(store, runs_dir, app, version, splunk, packages_dir, out=print):
        calls.append((app, version))
        if version == "1.0.0":
            return "rolled back to 1.0.0"
        raise promote.TransitionRefused(f"{app} {version}: the kept package does not match")

    monkeypatch.setattr(promote, "rollback", rollback)
    monkeypatch.setattr(api, "SplunkClient", lambda s: object())
    return calls


def test_rollback_checks_the_ta_and_version_exist_and_is_audited(pg, app, fake_rollback):
    from conftest import api_client, sign_in

    with api_client(app) as c:
        sign_in(c, pg.conn, "ops9")
        r = c.post(f"/tas/{APP}/rollback", json={"version": "1.0.0"})
        assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
        registered(pg)
        r = c.post(f"/tas/{APP}/rollback", json={"version": "9.9.9"})
        assert r.status_code == 404 and "no such version" in r.json()["error"]["message"]
        assert fake_rollback == []
        for bad in ({"version": "1.0"}, {"version": "1.0.0", "x": 1}, {}):
            assert c.post(f"/tas/{APP}/rollback", json=bad).status_code == 422
        assert c.post("/tas/Splunk_SA_CIM/rollback", json={"version": "1.0.0"}).status_code == 422
        r = c.post(f"/tas/{APP}/rollback", json={"version": "1.0.0"})
        assert r.status_code == 200 and r.json()["result"] == "rolled back to 1.0.0"
        assert fake_rollback == [(APP, "1.0.0")]
    rows = pg.conn.execute(
        "SELECT actor, outcome, detail FROM auth_events WHERE event = 'ta_rollback'"
    ).fetchall()
    assert [(r["actor"], r["outcome"], r["detail"]["version"]) for r in rows] == [
        ("ops9", "success", "1.0.0")
    ]


def test_cli_rollback_through_the_api_and_a_refusal(pg, run_cli, fake_rollback):
    raw = token(pg, "ops10", "admin")
    registered(pg)
    pg.conn.execute(
        "INSERT INTO ta_versions (app, version, job_id, sha256) VALUES (%s, '1.1.0', %s, %s)",
        (APP, "beef0001", "c" * 64),
    )
    code, out, err, seen = run_cli("rollback", APP, "1.0.0", raw=raw)
    assert code == 0 and "rolled back to 1.0.0" in out, err
    assert seen[0].full_url == f"{URL}/tas/{APP}/rollback"
    code, _, err, _ = run_cli("rollback", APP, "1.1.0", raw=raw)
    assert code == 4 and "does not match" in err and "HTTP 409" in err
    outcomes = pg.conn.execute(
        "SELECT outcome FROM auth_events WHERE event = 'ta_rollback' ORDER BY id"
    ).fetchall()
    assert [r["outcome"] for r in outcomes] == ["success", "failure"]
    code, _, err, _ = run_cli("rollback", "../../admin", "1.0.0", raw=raw)
    assert code == 4  # quoted into one path segment: refused by the route's pattern


# --- setup token in the container ----------------------------------------------------------------


def test_the_app_role_can_issue_the_setup_token(pg, tmp_path):
    """`docker compose exec engine parsemaxxing setup-token` runs as the app role (the engine
    container has no owner credentials)."""
    from parsemaxxing.auth.service import issue_setup_token

    pg.conn.execute("SET ROLE parsemaxxing_app")
    try:
        assert issue_setup_token(pg.conn, tmp_path / "setup-token", actor="cli:setup-token")
    finally:
        pg.conn.execute("RESET ROLE")
    assert (tmp_path / "setup-token").stat().st_mode & 0o777 == 0o600
