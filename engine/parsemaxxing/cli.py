"""parsemaxxing CLI. The CLI and the API share one orchestrator and one PostgreSQL queue.

Through the engine API (an API token: PARSEMAXXING_API_TOKEN or --token-file, mode 0600/0400;
URL: PARSEMAXXING_API_URL, default http://127.0.0.1:8080), so they get the API's role checks
and audit; the engine's worker pool does the work and the CLI waits for it:
  parsemaxxing run <file>                    queue a job and wait for it (auto-approved profile)
  parsemaxxing update <app> <file>           patch a promoted TA for new-format samples
  parsemaxxing approve <job> --sha256 <hash> approve exactly the validated package
  parsemaxxing reject <job>                  reject a run awaiting approval
  parsemaxxing promote <job>                 wait for the approved TA's promotion
  parsemaxxing rollback <app> <version>      reinstall an exact earlier version of a TA
  parsemaxxing kill on|off|status            the kill switch: stop claims and model calls

Read-only, straight from the database (app role): status <job>, tas.
The engine itself: worker [--id w1], serve [--workers 4].

Host-only, straight to the database by design: they must work when the API is down, before the
first admin exists, or need the owner account or the KEK, which the API never holds:
  parsemaxxing migrate                       apply migrations (database owner)
  parsemaxxing secrets rotate-kek --new-kek-file <path>  rewrap every vault data key
  parsemaxxing settings import-env [--env-file .env] [--dry-run]  move v1 .env values into
                                             settings and secrets into the vault (once)
  parsemaxxing ledger verify [--expect-head <id>:<hash>]  check the ledger hash chain (and
                                             that a recorded head is still in it)
  parsemaxxing ledger head                   print the newest row as <id>:<hash> (an anchor)
  parsemaxxing setup-token                   while no admin exists: a new one-time setup token
  parsemaxxing admin reset <user>            break-glass (database owner): new password, MFA
                                             cleared, unlocked, every session revoked
  parsemaxxing backup [--out-dir backups]    encrypted pg_dump (age, recipient from settings)
  parsemaxxing restore <file> --identity <age key> --target-dsn <dsn> --yes

`run --local` runs without PostgreSQL or the API (state in run records), as in Phases 2-4.
"""

import argparse
import dataclasses
import json
import logging
import os
import signal
import subprocess  # nosec B404 - only to start this CLI's own worker processes
import sys
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import quote

import psycopg

from parsemaxxing import config
from parsemaxxing.agents.llm import LLMClient, TokenCeilingExceeded
from parsemaxxing.api import intake
from parsemaxxing.config import REPO, Settings, database_url, load_env_file
from parsemaxxing.guardrails.index_time import GuardrailBlock
from parsemaxxing.ledger import store as db
from parsemaxxing.orchestrator import promote
from parsemaxxing.orchestrator.caps import IngestCaps
from parsemaxxing.orchestrator.run import run
from parsemaxxing.ta_builder.naming import require_job
from parsemaxxing.tools.splunk_client import SplunkClient

API_COMMANDS = ("run", "update", "approve", "reject", "promote", "rollback", "kill")
BUSY = ("queued", "running", "approved", "promoting")  # the engine's workers are on it
POLL_S = 2.0


def main(argv: list[str] | None = None, api_send=None) -> int:
    """`api_send`: the HTTP transport of the API commands (tests pass a TestClient-backed one)."""
    via = argparse.ArgumentParser(add_help=False)
    via.add_argument(
        "--token-file",
        type=Path,
        help="file holding the API token (mode 0600 or 0400); else PARSEMAXXING_API_TOKEN",
    )
    parser = argparse.ArgumentParser(
        prog="parsemaxxing",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    # The repo's .env, not the working directory's: a planted .env could redirect the tokens.
    parser.add_argument("--env-file", type=Path, default=REPO / ".env")
    sub = parser.add_subparsers(dest="command", required=True)
    r = sub.add_parser(
        "run",
        parents=[via],
        allow_abbrev=False,
        help="build and test a TA for one log file (through the API)",
    )
    r.add_argument("file", type=Path)
    r.add_argument("--tz", help="timezone of the logs, if known (IANA name)")
    r.add_argument("--vendor", help="vendor name, if known (e.g. acme)")
    r.add_argument("--product", help="product name, if known (e.g. vpn)")
    r.add_argument("--keep", action="store_true", help="leave the test app installed (--local)")
    r.add_argument("--max-attempts", type=int, help="--local only (else run.max_attempts)")
    r.add_argument("--stages", default="index-time,extraction,cim", help="comma-separated")
    r.add_argument(
        "--local",
        action="store_true",
        help="no PostgreSQL: state in run records; the kill switch and daily budget do not apply",
    )
    s = sub.add_parser("status", help="show a run")
    s.add_argument("job")
    a = sub.add_parser(
        "approve", parents=[via], allow_abbrev=False, help="approve exactly the validated package"
    )
    a.add_argument("job")
    a.add_argument("--sha256", required=True)
    j = sub.add_parser(
        "reject", parents=[via], allow_abbrev=False, help="reject a run awaiting approval"
    )
    j.add_argument("job")
    p = sub.add_parser(
        "promote", parents=[via], allow_abbrev=False, help="wait for the approved TA's promotion"
    )
    p.add_argument("job")
    w = sub.add_parser("worker", help="run one worker")
    w.add_argument("--id", default=f"w-{uuid.uuid4().hex[:6]}")
    w.add_argument("--parent", type=int, help="exit when this process (serve) is gone")
    v = sub.add_parser("serve", help="run the API and a pool of workers")
    v.add_argument("--workers", type=int, default=4)
    v.add_argument("--host", default="127.0.0.1")
    v.add_argument("--port", type=int, default=8080)
    sub.add_parser("migrate", help="apply migrations and set the app role's password (owner)")
    k = sub.add_parser("kill", parents=[via], allow_abbrev=False, help="the kill switch")
    k.add_argument("state", choices=["on", "off", "status"])
    sub.add_parser("tas", help="the TA registry")
    u = sub.add_parser(
        "update",
        parents=[via],
        allow_abbrev=False,
        help="patch a promoted TA for new-format samples",
    )
    u.add_argument("app")
    u.add_argument("file", type=Path)
    b = sub.add_parser(
        "rollback",
        parents=[via],
        allow_abbrev=False,
        help="reinstall an exact earlier version of a promoted TA",
    )
    b.add_argument("app")
    b.add_argument("version")
    sec = sub.add_parser("secrets", help="the secrets vault")
    sec_sub = sec.add_subparsers(dest="secrets_command", required=True)
    rk = sec_sub.add_parser("rotate-kek", help="rewrap every data key with a new KEK")
    rk.add_argument("--new-kek-file", type=Path, required=True)
    st = sub.add_parser("settings", help="the settings store")
    st_sub = st.add_subparsers(dest="settings_command", required=True)
    ie = st_sub.add_parser("import-env", help="one-time import of a v1 .env (secrets: vault)")
    ie.add_argument("--env-file", dest="import_file", type=Path, help="default: --env-file")
    ie.add_argument("--dry-run", action="store_true", help="show the diff, write nothing")
    lg = sub.add_parser("ledger", help="the ledger")
    lg_sub = lg.add_subparsers(dest="ledger_command", required=True)
    lv = lg_sub.add_parser("verify", help="check the hash chain (edited, removed or moved rows)")
    lv.add_argument("--expect-head", help="<id>:<hash> from `ledger head`: must still be there")
    lg_sub.add_parser("head", help="print the newest ledger row as <id>:<hash>")
    sub.add_parser(
        "setup-token",
        help="while no admin exists: a new one-time setup token (app role, no owner credentials)",
    )
    ad = sub.add_parser("admin", help="break-glass account recovery (database owner)")
    ad_sub = ad.add_subparsers(dest="admin_command", required=True)
    ar = ad_sub.add_parser("reset", help="new password, MFA cleared, sessions revoked")
    ar.add_argument("user")
    bk = sub.add_parser("backup", help="encrypted database backup (pg_dump | age)")
    bk.add_argument("--out-dir", type=Path, default=REPO / "backups")
    rs = sub.add_parser("restore", help="restore an encrypted backup into a database")
    rs.add_argument("file", type=Path)
    rs.add_argument("--identity", type=Path, required=True, help="age identity (private key) file")
    rs.add_argument("--target-dsn", required=True, help="the database to restore into")
    rs.add_argument("--yes", action="store_true", help="confirm: target objects are replaced")
    args = parser.parse_args(argv)

    load_env_file(args.env_file)
    logging.basicConfig(level=config.log_level())
    if args.command == "migrate":  # needs only the database owner, not the LLM or Splunk
        migrate()
        return 0
    if args.command == "secrets":  # needs only the database and the KEK files
        return rotate_kek(args.new_kek_file)
    if args.command == "settings":
        return import_env(args.import_file or args.env_file, args.dry_run)
    if args.command == "ledger":
        if args.ledger_command == "head":
            with db.connect(database_url()) as conn:
                print(db.ledger_head(conn))
            return 0
        return verify_ledger(args.expect_head)
    if args.command == "setup-token":
        return setup_token()
    if args.command == "admin":
        return admin_reset(args.user)
    if args.command in ("backup", "restore"):
        return backup_or_restore(args)
    local = args.command == "run" and args.local
    if args.command in API_COMMANDS and not local:
        return via_api(args, api_send)
    settings = config.runtime(local=local)
    if args.command == "run" and args.max_attempts:
        settings = dataclasses.replace(settings, max_attempts=args.max_attempts)
    try:
        if args.command == "run" and args.local:
            return local_run(args, settings)
        if args.command == "serve":
            migrate(optional=True)  # inside docker-compose the "migrate" service did this
            return serve(args)
        store = db.Store(db.connect(database_url()))
        if args.command == "tas":
            for t in store.tas():
                print(
                    f"{t['app']}  {t['sourcetype']}  current {t['current_version']}  "
                    f"versions {', '.join(t['versions'] or [])}"
                )
            return 0
        if args.command == "status":
            row = store.get(args.job)
            if row is None:
                print(f"no job {args.job}", file=sys.stderr)
                return 4
            print(
                json.dumps({k: row[k] for k in ("id", "status", "source_key", "tokens")}, indent=1)
            )
            print(
                json.dumps(
                    {k: v for k, v in (row["record"] or {}).items() if k != "events"}, indent=1
                )
            )
            for e in store.events(args.job):
                if e["event"] != "log":
                    print(f"  {e['at']:%Y-%m-%dT%H:%M:%S} {e['event']} {json.dumps(e['data'])}")
            return 0
        if args.command == "worker":
            from parsemaxxing.orchestrator.worker import Worker

            stop = threading.Event()
            signal.signal(signal.SIGTERM, lambda *_: stop.set())
            if args.parent:  # an orphaned worker must not keep claiming jobs unsupervised
                threading.Thread(target=watch_parent, args=(args.parent, stop), daemon=True).start()
            print(f"worker {args.id} started")
            Worker(settings, args.id).run_forever(stop)
            return 0
        raise AssertionError(args.command)  # every command is dispatched above
    except TokenCeilingExceeded as e:
        print(f"stopped: {e}", file=sys.stderr)
        return 3
    except (promote.TransitionRefused, GuardrailBlock, intake.UploadRefused, ValueError) as e:
        print(f"refused: {e}", file=sys.stderr)
        return 4


def watch_parent(pid: int, stop: threading.Event) -> None:
    while not stop.wait(5):
        if os.getppid() != pid:
            stop.set()


def migrate(optional: bool = False) -> None:
    """The only use of the owner account: schema changes and the app role's password."""
    try:
        admin = database_url(admin=True)
    except RuntimeError:
        if optional:
            print("migrations: skipped (no owner credentials here; run `parsemaxxing migrate`)")
            return
        raise
    with db.connect(admin) as conn:
        applied = db.migrate(conn)
        if password := config.app_password():
            db.set_app_password(conn, password)
            print("migrations:", applied or "up to date", "| app role: parsemaxxing_app")
        else:
            print(
                "migrations:",
                applied or "up to date",
                "| WARNING: POSTGRES_APP_PASSWORD not set; the engine uses the owner account",
            )


def rotate_kek(new_file: Path) -> int:
    """Rewrap every data key with the KEK in `new_file`, in one transaction. Stop the engine
    first: a running engine keeps the old KEK and is refused from then on."""
    from parsemaxxing.secrets import Kek, VaultError
    from parsemaxxing.secrets import rotate_kek as rotate

    current = config.kek_path()
    try:
        old, new = Kek.load(current), Kek.load(new_file)
        with db.connect(database_url()) as conn:
            n = rotate(conn, old, new, actor="cli:rotate-kek")
    except VaultError as e:
        print(f"refused: {e}", file=sys.stderr)
        return 4
    except psycopg.errors.InsufficientPrivilege:
        # psycopg's message can quote SQL; name only the cause (nothing was rewrapped).
        print(
            "refused: the database role lacks a privilege rotation needs; nothing was changed"
            " (run `parsemaxxing migrate` so the grants are current)",
            file=sys.stderr,
        )
        return 4
    except psycopg.Error as e:
        print(f"refused: database error ({type(e).__name__}); nothing was changed", file=sys.stderr)
        return 4
    print(f"rewrapped {n} data keys: KEK {old.id} -> {new.id}")
    print(f"now replace {current} with {new_file} (mode 0400), keep a backup, restart the engine")
    return 0


def import_env(env_file: Path, dry_run: bool) -> int:
    """One-time v1 import: plain values into settings, secrets into the vault. Shows the diff and
    the variables that can then be removed; never prints a secret value."""
    from parsemaxxing.secrets import Kek, VaultError

    values = config.read_env_file(env_file)
    if not values:
        print(f"nothing to import: no known keys in {env_file}", file=sys.stderr)
        return 4
    try:
        kek = Kek.load(config.kek_path())
    except VaultError as e:
        if not dry_run:
            print(f"refused: {e}", file=sys.stderr)
            return 4
        kek = None
    with db.connect(database_url()) as conn:
        try:
            lines, removable, ok = config.import_v1_env(
                conn, values, kek, dry_run, process_env=config.environ()
            )
        except (VaultError, ValueError) as e:  # SettingsError is a ValueError
            print(f"refused: {e}", file=sys.stderr)
            return 4
    print(f"{'dry run: ' if dry_run else ''}import of {env_file}:")
    print("\n".join(lines) or "  nothing to change")
    if removable:
        print(
            "can be removed from .env and the container environment once imported "
            "(a variable that stays overrides the stored setting): " + ", ".join(removable)
        )
    return 0 if ok else 4


def verify_ledger(expect_head: str | None = None) -> int:
    if expect_head is not None and not db.HEAD.fullmatch(expect_head):
        print("refused: --expect-head is <id>:<64 hex hash> (from `ledger head`)", file=sys.stderr)
        return 4
    from parsemaxxing.auth import events

    with db.connect(database_url()) as conn:
        result = db.verify_ledger(conn, expect_head=expect_head)
        audit = events.verify(conn)
    for p in result["problems"]:
        print(f"  row {p['id']}: {p['problem']}")
    for p in audit["problems"]:
        print(f"  auth_events row {p['id']}: {p['problem']}")
    head = result["head"]
    print(f"{result['rows']} rows; head {head['id']} {head['hash']}")
    print(f"auth_events: {audit['rows']} rows; head {audit['head']['id']} {audit['head']['hash']}")
    if result["problems"] or audit["problems"]:
        print("ledger verify: FAILED", file=sys.stderr)
        return 5
    print("ledger verify: ok")
    return 0


def setup_token() -> int:
    """Print a fresh setup token (to this terminal, never a log) and the file it is in."""
    from parsemaxxing.auth.service import issue_setup_token

    path = promote.runs_root(config.runs_dir()) / "setup-token"
    with db.connect(database_url()) as conn:
        token = issue_setup_token(conn, path, actor="cli:setup-token")
    if token is None:
        print("refused: setup is complete (an admin exists); use `admin reset`", file=sys.stderr)
        return 4
    print(f"setup token (valid 60 minutes, single use; also in {path}):")
    print(token)
    return 0


def admin_reset(user: str) -> int:
    """Break-glass: needs the database owner's credentials on the host. The new password is
    read without echo and never printed."""
    import getpass

    from parsemaxxing.auth.model import AuthError
    from parsemaxxing.auth.service import admin_reset as reset

    password = getpass.getpass(f"new password for {user}: ")
    if getpass.getpass("again: ") != password:
        print("refused: the passwords differ", file=sys.stderr)
        return 4
    try:
        with db.connect(database_url(admin=True)) as conn:
            row = reset(conn, user, password)
    except AuthError as e:
        print(f"refused: {e.message}", file=sys.stderr)
        return 4
    except psycopg.Error as e:
        print(f"refused: database error ({type(e).__name__})", file=sys.stderr)
        return 4
    print(
        f"{row['username']}: password reset, MFA cleared (enrol again at sign-in), sessions revoked"
    )
    return 0


def backup_or_restore(args) -> int:
    from parsemaxxing.ledger import backup
    from parsemaxxing.settings import PLATFORM, BackupSettings, SettingsService

    try:
        if args.command == "restore":
            if not args.yes:
                print("refused: restore replaces objects in the target; add --yes", file=sys.stderr)
                return 4
            result = backup.restore(args.file, args.identity, args.target_dsn, config.environ())
            print(f"restored {args.file.name}; ledger verified ({result['rows']} rows)")
            return 0
        dsn = database_url(admin=True)  # the owner sees every table
        with db.connect(dsn) as conn:
            recipient = SettingsService(conn, config.environ()).get(BackupSettings, PLATFORM)
            head = db.ledger_head(conn)  # before the dump starts: the dump contains this row
        if not recipient.age_recipient:
            print("refused: set backup.age_recipient (an age public key) first", file=sys.stderr)
            return 4
        path = backup.backup(dsn, recipient.age_recipient, args.out_dir, config.environ(), head)
    except (backup.BackupError, OSError) as e:
        print(f"refused: {e}", file=sys.stderr)
        return 4
    except psycopg.Error as e:  # its message can quote SQL or connection details
        print(f"refused: database error ({type(e).__name__})", file=sys.stderr)
        return 4
    print(f"backup written: {path} (+ .sha256); ledger head {head}")
    return 0


def via_api(args, send=None) -> int:
    """A mutating command through the engine API with an API token (never printed)."""
    from parsemaxxing.api.client import Api, ApiError

    try:
        api = Api(config.api_url(), config.api_token(args.token_file), send)
        return API_HANDLERS[args.command](api, args)
    except ApiError as e:
        print(f"refused: {e}", file=sys.stderr)
        return 4
    except (RuntimeError, ValueError, intake.UploadRefused) as e:  # our own, client-safe
        print(f"refused: {e}", file=sys.stderr)
        return 4
    except OSError as e:
        print(f"refused: cannot read a file ({type(e).__name__})", file=sys.stderr)
        return 4


def _wait(api, job: str) -> dict:
    """The run once the engine's workers are done with it (Ctrl-C stops waiting, not the run)."""
    while (row := api.call("GET", f"/runs/{job}"))["status"] in BUSY:
        time.sleep(POLL_S)
    return row


def api_run(api, args) -> int:
    """Upload the file like the UI (the engine checks it), then wait for the run."""
    if args.command == "run" and args.max_attempts:
        raise ValueError("--max-attempts needs --local; queued runs use run.max_attempts")
    files = {"file": (intake.safe_name(args.file.name), args.file.read_bytes())}
    beside = args.file.with_suffix(".manifest.json")
    if beside.is_file():
        files["manifest"] = ("manifest.json", beside.read_bytes())
    fields = {"auto_approve": "true"}
    if args.command == "update":
        fields["update_of"] = args.app
    else:
        fields |= {n: getattr(args, n) for n in ("vendor", "product", "tz") if getattr(args, n)}
    out = api.call("POST", "/uploads", fields=fields, files=files)
    job = require_job(out["job"])
    if out["duplicate"]:
        print(f"duplicate of job {job}: nothing to do")
        return 0
    print(f"job {job} queued (~{out['estimated_tokens']} tokens estimated)")
    row = _wait(api, job)
    record = row.get("record") or {}
    print(f"{job}: {row['status']} {record.get('result', '')}".rstrip())
    if row["status"] == "awaiting_approval":
        print(f"approve: parsemaxxing approve {job} --sha256 {record.get('sha256_test')}")
    elif row["status"] == "profile_review":
        print("the run needs a profile review (for example its timezone) in the UI")
    return 0 if row["status"] in ("awaiting_approval", "done") else 1


def api_approve(api, args) -> int:
    job = require_job(args.job)
    print(api.call("POST", f"/runs/{job}/approve", {"sha256": args.sha256})["result"])
    return 0


def api_reject(api, args) -> int:
    job = require_job(args.job)
    print(f"{job}: {api.call('POST', f'/runs/{job}/reject', {})['status']}")
    return 0


def api_promote(api, args) -> int:
    """Approval queues the promotion for the engine's workers; this waits for it."""
    job = require_job(args.job)
    if api.call("GET", f"/runs/{job}")["status"] not in ("approved", "promoting", "done"):
        raise ValueError("run is not approved")
    row = _wait(api, job)
    print(f"{job}: {row['status']} {(row.get('record') or {}).get('smoke', '')}".rstrip())
    return 0 if row["status"] == promote.DONE else 1


def api_rollback(api, args) -> int:
    path = f"/tas/{quote(args.app, safe='')}/rollback"
    print(api.call("POST", path, {"version": args.version}, timeout=600)["result"])
    return 0


def api_kill(api, args) -> int:
    if args.state != "status":
        api.call("POST", "/admin/kill", {"on": args.state == "on"})
    out = api.call("GET", "/admin/status")
    state = "on" if out["kill_switch"] else "off"
    print(f"kill switch: {state}; tokens today {out['tokens_today']}")
    return 0


API_HANDLERS = {
    "run": api_run,
    "update": api_run,
    "approve": api_approve,
    "reject": api_reject,
    "promote": api_promote,
    "rollback": api_rollback,
    "kill": api_kill,
}


def local_run(args, settings: Settings) -> int:
    caps = IngestCaps(settings.runs_dir, settings.job_ingest_mb, settings.daily_ingest_mb)
    result = run(
        args.file,
        LLMClient(settings),
        SplunkClient(settings),
        settings.test_index,
        settings.packages_dir,
        timezone=args.tz,
        vendor=args.vendor,
        product=args.product,
        keep=args.keep,
        max_attempts=settings.max_attempts,
        stages=tuple(args.stages.split(",")),
        runs_dir=settings.runs_dir,
        caps=caps,
    )
    return 0 if result.status == "passed" else 1


def serve(args) -> int:
    """The API (uvicorn) plus a pool of worker processes; workers restart if they exit."""
    import uvicorn

    from parsemaxxing.api.app import create_app

    me = [sys.executable, "-m", "parsemaxxing.cli", "--env-file", str(args.env_file)]

    def start(name: str) -> subprocess.Popen:
        # Fixed arguments: this CLI's own interpreter and module, a generated worker id.
        argv = [*me, "worker", "--id", f"{name}-{os.getpid()}", "--parent", str(os.getpid())]
        return subprocess.Popen(argv)  # noqa: S603  # nosec B603

    procs = {f"w{i}": start(f"w{i}") for i in range(1, args.workers + 1)}
    stop = threading.Event()

    def supervise() -> None:
        while not stop.wait(5):
            for name, proc in list(procs.items()):
                if proc.poll() is not None:  # auto-restart policy (design "Operation never stops")
                    procs[name] = start(name)

    threading.Thread(target=supervise, daemon=True).start()
    try:
        uvicorn.run(create_app(), host=args.host, port=args.port, proxy_headers=False)
    finally:
        stop.set()
        for proc in procs.values():
            proc.terminate()
    return 0


if __name__ == "__main__":
    sys.exit(main())
