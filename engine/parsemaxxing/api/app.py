"""HTTP API for the UI and the CLI: upload, runs, profile review, approve/reject, package
download, TA rollback, and a server-sent event stream of the ledger (design "Platform and UI").

Every route has a role policy (auth/policy.py, deny by default: the app refuses to build with
a route that has none) and needs a session cookie or an API token unless it is in
auth.policy.PUBLIC. CORS allows only the web origin, the Host header must be a known name (DNS
rebinding, T8.5), every state-changing request needs the custom header and, when it carries a
session cookie, an allowed Origin; every response carries security headers and an X-Request-ID.
Every error is one envelope,
{"error": {"code", "message", "request_id"}, "detail": message} ("detail" for the v1 web UI);
unexpected errors say only "internal error" and are logged with the request id. All SQL goes
through the parameterised Store.
"""

import asyncio
import ipaddress
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import contextmanager
from functools import cache, partial
from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi import Path as PathParam
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from parsemaxxing import config
from parsemaxxing.api import intake
from parsemaxxing.auth import events as audit
from parsemaxxing.auth import policy
from parsemaxxing.auth.model import AuthError
from parsemaxxing.auth.policy import Admin, StoreDep, Viewer, client_ip
from parsemaxxing.auth.routes import router as auth_router
from parsemaxxing.auth.service import issue_setup_token
from parsemaxxing.config import REPO, Settings, load_env_file
from parsemaxxing.ledger import store as db
from parsemaxxing.orchestrator import promote
from parsemaxxing.orchestrator.worker import apply_corrections
from parsemaxxing.secrets import Kek
from parsemaxxing.tools.splunk_client import SplunkClient, SplunkError

log = logging.getLogger("parsemaxxing.api")
JobId = Annotated[str, PathParam(pattern=r"^[a-z0-9]{4,16}$")]
TaName = Annotated[
    str, PathParam(pattern=r"^TA-(parsemaxxing|parsewright)-[a-z0-9_:-]+$", max_length=120)
]
CSRF_HEADER = "X-Parsemaxxing"
MAX_BODY = 31 * 1024 * 1024  # 10 MB sample + 20 MB manifest + form overhead
MAX_STREAMS = 20
RECHECK_S = 15  # an open event stream re-checks its session or token this often
STREAMS = asyncio.Semaphore(MAX_STREAMS)
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "Cross-Origin-Resource-Policy": "same-origin",
}
REQUEST_ID = "X-Request-ID"
CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    422: "invalid_request",
    429: "too_many_requests",
    502: "bad_gateway",
    503: "unavailable",
}


def error(
    status: int, message: str, request_id: str = "", headers: dict | None = None
) -> JSONResponse:
    """The one error envelope. `message` is written for the client: never SQL, paths or
    stack traces (those go to the log with the request id)."""
    body = {
        "error": {
            "code": CODES.get(status, "internal_error" if status >= 500 else "error"),
            "message": message,
            "request_id": request_id,
        },
        "detail": message,  # v1 web UI reads this; remove once web/lib/api.ts reads "error"
    }
    out = {**SECURITY_HEADERS, **(headers or {})}
    if request_id:
        out[REQUEST_ID] = request_id
    return JSONResponse(body, status, headers=out)


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "")


def create_app(
    settings: Settings | None = None,
    dsn: str | None = None,
    migrate: bool = False,
    kek: Kek | None = None,
) -> FastAPI:
    """`kek`: the vault key (tests); by default it is loaded from the KEK file at first use."""
    if settings is None:
        load_env_file(REPO / ".env")
        settings = config.runtime()
    dsn = dsn or settings.dsn or config.database_url()
    if migrate:  # only with the owner's credentials (tests, local); the engine runs as the app role
        with db.connect(dsn) as conn:
            db.migrate(conn)
    uploads = promote.runs_root(settings.runs_dir) / "uploads"
    uploads.mkdir(mode=0o700, exist_ok=True)

    app = FastAPI(title="Parsemaxxing", docs_url=None, redoc_url=None, openapi_url=None)
    web_origins = config.web_origins()
    hosts = set(config.allowed_hosts())
    app.state.dsn = dsn
    app.state.environ = config.environ()
    app.state.kek = (lambda: kek) if kek is not None else _kek_loader()
    app.state.trusted_proxies = [ipaddress.ip_network(n) for n in config.trusted_proxies()]
    app.state.setup_token_path = promote.runs_root(settings.runs_dir) / "setup-token"
    with db.connect(dsn) as conn:
        if issue_setup_token(conn, app.state.setup_token_path):
            # The path only, never the token (design 7.3 "First run").
            log.warning(  # nosemgrep: python-logger-credential-disclosure
                "no admin account yet: a one-time setup token (valid 60 minutes) is in %s",
                app.state.setup_token_path,
            )
    app.add_middleware(BodyLimit, limit=MAX_BODY, paths=("/uploads",))
    app.add_middleware(
        CORSMiddleware,
        allow_origins=web_origins,
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=["Content-Type", "Last-Event-ID", CSRF_HEADER],
    )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        message = exc.detail if isinstance(exc.detail, str) else "request refused"
        return error(exc.status_code, message, _request_id(request), exc.headers)

    @app.exception_handler(AuthError)
    async def auth_error(request: Request, exc: AuthError) -> JSONResponse:
        retry = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
        return error(exc.status, exc.message, _request_id(request), retry)

    @app.exception_handler(RequestValidationError)
    async def invalid(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Field locations only: Pydantic's messages can echo the submitted value.
        fields = sorted({".".join(str(p) for p in e["loc"][1:]) or "body" for e in exc.errors()})
        # Logged without the input either: a refused body may hold a secret.
        # repr: a loc entry can be a client-chosen key (an extra field) holding a newline.
        problems = "; ".join(
            f"{'.'.join(repr(p) for p in e['loc'])} {e['type']}" for e in exc.errors()
        )
        log.info("request %s invalid: %s", _request_id(request), problems)
        return error(422, f"invalid request: {', '.join(fields)}", _request_id(request))

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        rid = uuid.uuid4().hex  # never taken from the client: it keys our logs
        request.state.request_id = rid
        # DNS rebinding (T8.5): only known Host names.
        if request.headers.get("host", "").split(":")[0] not in hosts:
            return error(400, "unknown host", rid)
        # CSRF (T8.3): a state-changing request needs a custom header, which a cross-site page
        # can only send after a CORS preflight that names this origin; a foreign Origin is
        # refused outright. A plain multipart form POST from another site is "simple" and
        # would otherwise go through without a preflight (appsec Phase 5 H1).
        # Phase 13: a request that carries the session cookie must also carry an Origin (browsers
        # send one on every POST), so a cookie can never ride on an Origin-less request.
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            cookie = policy.SESSION_COOKIE in request.cookies
            if (
                request.headers.get(CSRF_HEADER) != "1"
                or (origin and origin not in web_origins)
                or (cookie and not origin)
            ):
                return error(403, "cross-site request refused", rid)
        # Deny by default before any body is read: no credential, no route (except PUBLIC).
        if (
            request.method != "OPTIONS"
            and (request.method, request.url.path) not in policy.PUBLIC
            and "authorization" not in request.headers
            and policy.SESSION_COOKIE not in request.cookies
        ):
            return error(401, "Sign in first.", rid)
        try:
            response = await call_next(request)
        except Exception as exc:  # noqa: BLE001 - every error becomes the 500 envelope
            # The type only: a traceback or message can quote SQL, psycopg DETAIL (row values)
            # or a path.
            log.error("request %s failed: %s", rid, type(exc).__name__)
            return error(500, "internal error", rid)
        response.headers.update(SECURITY_HEADERS)
        response.headers[REQUEST_ID] = rid
        return response

    @contextmanager
    def connection() -> Iterator[db.Store]:
        conn = db.connect(dsn)
        try:
            yield db.Store(conn)
        finally:
            conn.close()

    def job_or_404(store: db.Store, job: str) -> dict:
        row = store.get(job)
        if row is None:
            raise HTTPException(404, "no such run")
        return row

    app.include_router(auth_router)

    @app.get("/health")
    def health(store: StoreDep) -> dict:
        store.conn.execute("SELECT 1")
        return {"status": "ok"}

    # --- intake ------------------------------------------------------------------------

    @app.post("/uploads", status_code=201)
    async def upload(
        who: Admin,
        store: StoreDep,
        file: Annotated[UploadFile, File()],
        manifest: Annotated[UploadFile | None, File()] = None,
        vendor: Annotated[str | None, Form(max_length=40)] = None,
        product: Annotated[str | None, Form(max_length=40)] = None,
        tz: Annotated[str | None, Form(max_length=64)] = None,
        auto_approve: Annotated[bool, Form()] = False,
        update_of: Annotated[str | None, Form(max_length=120)] = None,
    ) -> dict:
        try:
            name = intake.safe_name(file.filename or "")
            sample = intake.check(await file.read(intake.MAX_BYTES + 1))
            truth = await _manifest(manifest, sample)
            form = _form(vendor, product, tz, auto_approve) | {"file_name": name}
            if update_of:  # a parser update: only a TA Parsemaxxing promoted (the registry)
                ta = store.ta(update_of)
                if ta is None:
                    raise intake.UploadRefused(
                        "update_of must be a TA in the registry (built by Parsemaxxing)"
                    )
                form = {"update_of": ta["app"], "file_name": name, "auto_approve": True}
            estimate = intake.estimate_tokens(sample)
            if estimate > settings.run_token_ceiling:
                raise intake.UploadRefused(
                    f"estimated {estimate} tokens is over the per-run ceiling "
                    f"({settings.run_token_ceiling})"
                )
        except intake.UploadRefused as e:
            raise HTTPException(422, f"upload refused: {e}") from None
        # Fixed names in a fresh per-job folder (appsec M2): no user-derived path, no reuse.
        job = uuid.uuid4().hex[:8]
        path, digest = intake.save(
            uploads, job, sample, json.dumps(truth).encode("utf-8") if truth else None
        )
        # fixture: the repo's own answer key; uploaded: an untrusted one, checked; mechanical: none
        form["validation"] = (
            ("uploaded" if manifest is not None else "fixture") if truth else "mechanical"
        )
        if digest:
            form["manifest_sha256"] = digest
        if form.get("update_of"):
            key = f"update:{form['update_of']}"  # one active update per TA
        elif form.get("vendor") and form.get("product"):
            key = f"{form['vendor']}:{form['product']}"
        else:
            key = f"upload:{sample.sha256[:16]}"
        job_id, duplicate = store.enqueue(
            job, key, sample.sha256, str(path), form, created_by=who.username
        )
        return {
            "job": job_id,
            "duplicate": duplicate,
            "events": sample.events,
            "estimated_tokens": estimate,
        }

    # --- runs --------------------------------------------------------------------------

    @app.get("/runs")
    def runs(_: Viewer, store: StoreDep) -> list[dict]:
        return [_public(r) for r in store.jobs()]

    @app.get("/runs/{job}")
    def get_run(job: JobId, _: Viewer, store: StoreDep) -> dict:
        return _public(job_or_404(store, job), detail=True)

    @app.get("/runs/{job}/events")
    def ledger(job: JobId, _: Viewer, store: StoreDep, after: int = 0) -> list[dict]:
        job_or_404(store, job)
        return [_event(e) for e in store.events(job, after)]

    class Corrections(BaseModel):
        model_config = ConfigDict(extra="forbid")

        vendor: str | None = Field(None, max_length=40)
        product: str | None = Field(None, max_length=40)
        sourcetype: str | None = Field(None, max_length=80)
        tz: str | None = Field(None, max_length=64)

    @app.post("/runs/{job}/profile")
    def confirm_profile(job: JobId, body: Corrections, _: Admin, store: StoreDep) -> dict:
        row = job_or_404(store, job)
        if row["status"] != "profile_review":
            raise HTTPException(409, f"run is {row['status']}, not profile_review")
        state = dict(row["state"])
        try:
            state["profile"] = apply_corrections(state["profile"], body.model_dump())
        except ValueError as e:
            raise HTTPException(422, str(e)) from None
        # The run found timestamps with no zone (decided by code, recorded in its state): only a
        # timezone the human sends here counts; the AI's hint never does (appsec M2).
        if state.get("needs_timezone") and not body.tz:
            raise HTTPException(422, "choose the timezone the timestamps are written in")
        if body.tz:
            state["tz_confirmed"] = state["profile"]["timezone_hint"]  # validated just above
        state["profile_confirmed"] = True
        state.pop("needs_timezone", None)
        if not store.transition(job, "profile_review", "queued", state=state):
            raise HTTPException(409, "the run changed state; reload and try again")
        return {"job": job, "status": "queued"}

    class Approval(BaseModel):
        model_config = ConfigDict(extra="forbid")

        sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @app.post("/runs/{job}/approve")
    def approve(job: JobId, body: Approval, who: Admin, request: Request, store: StoreDep) -> dict:
        job_or_404(store, job)
        records = promote.PgRecords(store.conn, settings.runs_dir)
        try:
            result = promote.approve(records, job, body.sha256)
        except promote.TransitionRefused as e:
            raise HTTPException(409, str(e)) from None
        audit.record(
            store.conn,
            "run_approve",
            "success",
            who.username,
            who.user_id,
            client_ip(request),
            job=job,
            sha256=body.sha256,
        )
        return {"job": job, "result": result}

    @app.post("/runs/{job}/reject")
    def reject(job: JobId, who: Admin, request: Request, store: StoreDep) -> dict:
        job_or_404(store, job)
        if not store.transition(job, "awaiting_approval", "rejected"):
            raise HTTPException(409, "only a run awaiting approval can be rejected")
        audit.record(
            store.conn,
            "run_reject",
            "success",
            who.username,
            who.user_id,
            client_ip(request),
            job=job,
        )
        return {"job": job, "status": "rejected"}

    @app.get("/runs/{job}/package")
    def download(job: JobId, _: Viewer, store: StoreDep) -> FileResponse:
        row = job_or_404(store, job)
        folder = promote.runs_root(settings.runs_dir) / job
        name = "promoted.tgz" if row["status"] == "done" else "test.tgz"
        path = folder / name
        if (
            row["status"] not in ("awaiting_approval", "approved", "promoting", "done")
            or not path.is_file()
            or path.is_symlink()
        ):
            raise HTTPException(404, "no package for this run yet")
        app_name = (
            row["record"].get("app") if name == "promoted.tgz" else row["record"].get("test_app")
        )
        return FileResponse(path, media_type="application/gzip", filename=f"{app_name}.tgz")

    # --- TA registry ---------------------------------------------------------------------

    @app.get("/tas")
    def tas(_: Viewer, store: StoreDep) -> list[dict]:
        return [
            {
                "app": t["app"],
                "sourcetype": t["sourcetype"],
                "current_version": t["current_version"],
                "versions": t["versions"] or [],
                "updated_at": str(t["updated_at"]),
            }
            for t in store.tas()
        ]

    class Rollback(BaseModel):
        model_config = ConfigDict(extra="forbid")

        version: str = Field(pattern=r"^\d{1,6}\.\d{1,6}\.\d{1,6}$")

    @app.post("/tas/{app_name}/rollback")
    def rollback(
        app_name: TaName, body: Rollback, who: Admin, request: Request, store: StoreDep
    ) -> dict:
        """Reinstall an exact earlier registered version (its kept, hash-checked bytes)."""
        if store.ta(app_name) is None:
            raise HTTPException(404, "no such TA in the registry")
        if not any(v["version"] == body.version for v in store.ta_versions(app_name)):
            raise HTTPException(404, "no such version of this TA")

        def outcome(result: str, **detail) -> None:
            audit.record(
                store.conn,
                "ta_rollback",
                result,
                who.username,
                who.user_id,
                client_ip(request),
                app=app_name,
                version=body.version,
                **detail,
            )

        try:
            message = promote.rollback(
                store,
                settings.runs_dir,
                app_name,
                body.version,
                SplunkClient(settings),
                settings.packages_dir,
                out=lambda line, *_: log.info("rollback %s: %s", app_name, line),
            )
        except promote.TransitionRefused as e:  # its messages are written for the operator
            outcome("failure", reason=type(e).__name__)
            raise HTTPException(409, str(e)) from None
        except (SplunkError, ValueError, RuntimeError) as e:  # these can name paths: log only
            outcome("failure", reason=type(e).__name__)
            log.warning("request %s: rollback refused: %s", _request_id(request), type(e).__name__)
            status = 502 if isinstance(e, SplunkError) else 409
            raise HTTPException(status, "rollback refused; see the engine log") from None
        outcome("success")
        return {"app": app_name, "version": body.version, "result": message}

    # --- live stream ---------------------------------------------------------------------

    @app.get("/runs/{job}/stream")
    async def stream(job: JobId, _: Viewer, request: Request) -> StreamingResponse:
        with connection() as s:
            job_or_404(s, job)
        start = request.headers.get("last-event-id", "0")
        after = int(start) if start.isdigit() else 0
        if STREAMS.locked():
            raise HTTPException(503, "too many open event streams")
        return StreamingResponse(
            _capped(_sse(dsn, job, after, request, partial(_still_viewer, request))),
            media_type="text/event-stream",
            headers={"X-Accel-Buffering": "no"},
        )

    # --- operator ------------------------------------------------------------------------

    class Kill(BaseModel):
        model_config = ConfigDict(extra="forbid")

        on: bool

    @app.get("/admin/status")
    def admin_status(_: Viewer, store: StoreDep) -> dict:
        return {"kill_switch": store.kill_switch(), "tokens_today": store.tokens_today()}

    @app.post("/admin/kill")
    def kill(body: Kill, who: Admin, request: Request, store: StoreDep) -> dict:
        store.set_kill_switch(body.on)
        audit.record(
            store.conn,
            "kill_switch",
            "success",
            who.username,
            who.user_id,
            client_ip(request),
            on=body.on,
        )
        return {"kill_switch": store.kill_switch()}

    policy.check_routes(app)  # fail closed: a route without a role policy stops the engine
    return app


def _kek_loader() -> Callable[[], Kek]:
    @cache
    def load() -> Kek:
        return Kek.load(config.kek_path())

    return load


async def _capped(gen: AsyncIterator[bytes]) -> AsyncIterator[bytes]:
    """Each stream holds a PostgreSQL connection: at most MAX_STREAMS at once (appsec L10)."""
    async with STREAMS:
        async for chunk in gen:
            yield chunk


class BodyLimit:
    """Refuse oversized request bodies before they are parsed or spooled to disk (appsec M4):
    Content-Length is required on the limited paths, and the bytes received are counted."""

    def __init__(self, app, limit: int, paths: tuple[str, ...]):
        self.app, self.limit, self.paths = app, limit, paths

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith(self.paths):
            return await self.app(scope, receive, send)
        length = dict(scope["headers"]).get(b"content-length", b"")
        if not length.isdigit() or int(length) > self.limit:
            rid = scope.get("state", {}).get("request_id", "")
            response = error(413, "request body too large or of unknown size", rid)
            return await response(scope, receive, send)
        seen = 0

        async def counted():
            nonlocal seen
            message = await receive()
            seen += len(message.get("body", b""))
            if seen > self.limit:
                raise HTTPException(413, "request body too large")
            return message

        return await self.app(scope, counted, send)


def _still_viewer(request: Request, store: db.Store) -> bool:
    """The stream's credential is still valid and still passes the route's Viewer policy
    (not revoked, expired, disabled or demoted below it). Not counted as session activity."""
    rule = policy.VIEWER.pmx_policy
    try:
        p = policy.authenticate(request, policy.auth_for(request, store), touch=False)
    except AuthError:
        return False
    return p.stage in rule.stages and p.role.covers(rule.role)


async def _sse(
    dsn: str,
    job: str,
    after: int,
    request: Request,
    allowed: Callable[[db.Store], bool],
) -> AsyncIterator[bytes]:
    """Replay the job's ledger after `after`, then push each new row as it is inserted.
    Every RECHECK_S the caller's credential is checked again; the stream ends once it fails."""
    loop = asyncio.get_running_loop()
    conn = await loop.run_in_executor(None, db.connect, dsn)
    try:
        await loop.run_in_executor(None, conn.execute, "LISTEN ledger")
        store = db.Store(conn)
        checked = time.monotonic()
        while not await request.is_disconnected():
            if time.monotonic() - checked >= RECHECK_S:
                if not await loop.run_in_executor(None, allowed, store):
                    return
                checked = time.monotonic()
            rows = await loop.run_in_executor(None, store.events, job, after)
            for e in rows:
                after = e["id"]
                yield f"id: {e['id']}\nevent: ledger\ndata: {json.dumps(_event(e))}\n\n".encode()
            notes = await loop.run_in_executor(
                None, lambda: list(conn.notifies(timeout=1.0, stop_after=1))
            )
            if not notes and not rows:
                yield b": keep-alive\n\n"
    finally:
        conn.close()


async def _manifest(upload: UploadFile | None, sample: intake.Sample) -> dict | None:
    """A truth manifest, if there is one: uploaded, or found for a generator sample by its
    content. Untrusted either way, so checked. None: the log is validated mechanically."""
    raw = (
        await upload.read(20 * 1024 * 1024 + 1)
        if upload is not None
        else intake.fixture_manifest(sample)
    )
    if raw is None:
        return None
    try:
        truth = json.loads(raw)
    except (ValueError, RecursionError):
        raise intake.UploadRefused("the manifest is not JSON") from None
    epochs = truth.get("epochs") if isinstance(truth, dict) else None
    events = truth.get("events") if isinstance(truth, dict) else None
    if (
        not isinstance(epochs, list)
        or not all(isinstance(e, int) for e in epochs)
        or truth.get("event_count") != len(epochs)
        or not isinstance(events, list)
    ):
        raise intake.UploadRefused("the manifest needs event_count, epochs and events")
    if len(epochs) != sample.events:
        raise intake.UploadRefused("the manifest's event count does not match the file")
    # The manifest is the Validator's ground truth: every event must be described, matching
    # the epochs, or an empty or foreign events list could leave the CIM stage nothing to
    # check (appsec Phase 5 M1).
    if len(events) != len(epochs) or not all(_event_ok(e) for e in events):
        raise intake.UploadRefused("each manifest event needs epoch, category, fields and cim")
    if sorted(e["epoch"] for e in events) != sorted(epochs):
        raise intake.UploadRefused("the manifest's events do not match its epochs")
    return truth


def _event_ok(e: object) -> bool:
    def str_map(m: object) -> bool:
        return isinstance(m, dict) and all(
            isinstance(k, str) and isinstance(v, str) for k, v in m.items()
        )

    return (
        isinstance(e, dict)
        and isinstance(e.get("epoch"), int)
        and isinstance(e.get("category"), str)
        and str_map(e.get("fields"))
        and str_map(e.get("cim"))
    )


def _form(vendor, product, tz, auto_approve) -> dict:
    from parsemaxxing.agents.profiler import clean_name
    from parsemaxxing.guardrails.index_time import ALLOWED, GuardrailBlock

    form: dict = {"auto_approve": bool(auto_approve)}
    if vendor:
        form["vendor"] = clean_name(vendor)
    if product:
        form["product"] = clean_name(product)
    if tz:
        try:
            form["tz"] = ALLOWED["TZ"](tz)
        except GuardrailBlock as e:
            raise intake.UploadRefused(f"tz {e}") from None
    return form


def _event(e: dict) -> dict:
    return {"id": e["id"], "at": str(e["at"]), "event": e["event"], "data": e["data"]}


def _public(row: dict, detail: bool = False) -> dict:
    out = {
        "job": row["id"],
        "status": row["status"],
        "source_key": row["source_key"],
        "created_by": row.get("created_by"),
        "form": row["form"],
        "tokens": row.get("tokens", 0),
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
    }
    if detail:
        state, record = row.get("state") or {}, row.get("record") or {}
        out["profile"] = state.get("profile")
        out["stage_index"] = state.get("stage_index")
        out["needs_timezone"] = bool(state.get("needs_timezone"))
        out["record"] = {
            k: v
            for k, v in record.items()
            if k
            in (
                "app",
                "test_app",
                "sourcetype",
                "sha256_test",
                "approved_sha256",
                "sha256_promoted",
                "smoke",
                "events",
                "report",
                "kind",
                "update_of",
                "version_from",
                "version_to",
                "result",
            )
        }
    return out
