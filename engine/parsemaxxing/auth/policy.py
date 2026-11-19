"""The route policy registry (design 7.3, principle "deny by default").

Every route either depends on `require(Role.X)` or is listed in PUBLIC. `check_routes(app)`
runs when the app is built and refuses to start on any route with neither (or both), and the
route-inventory test calls it too. Authorization lives only here, in the engine.
"""

import ipaddress
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, FastAPI, Request, Response
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute

from parsemaxxing.auth.model import ALL_STAGES, AuthError, Principal, Role, Stage
from parsemaxxing.auth.service import Auth, _key
from parsemaxxing.ledger import store as db
from parsemaxxing.settings import PLATFORM, AuthSettings, SettingsService

SESSION_COOKIE = "__Host-pmx_session"
# The only routes reachable without signing in. Exact (method, path): none has a path parameter.
PUBLIC: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", "/health"),
        ("GET", "/setup"),  # is first-run setup still needed?
        ("POST", "/setup"),  # needs the one-time setup token
        ("POST", "/auth/login"),
        ("POST", "/auth/logout"),  # revokes the cookie's session if any, always clears it
    }
)


@dataclass(frozen=True)
class Policy:
    role: Role
    session_only: bool  # API tokens refused (account security, token creation, users)
    stages: tuple[Stage, ...]


def get_store(request: Request) -> Iterator[db.Store]:
    """The request's database connection, shared by the policy check and the route."""
    conn = db.connect(request.app.state.dsn)
    try:
        yield db.Store(conn)
    finally:
        conn.close()


StoreDep = Annotated[db.Store, Depends(get_store)]


def auth_for(request: Request, store: db.Store) -> Auth:
    settings = SettingsService(store.conn, request.app.state.environ).get(AuthSettings, PLATFORM)
    return Auth(store.conn, settings, request.app.state.kek, request.app.state.environ)


def client_ip(request: Request) -> str:
    """The TCP peer, or the last X-Forwarded-For hop when the peer is a trusted proxy."""
    peer = request.client.host if request.client else ""
    forwarded = request.headers.get("x-forwarded-for", "")
    trusted = request.app.state.trusted_proxies
    try:
        if forwarded and any(ipaddress.ip_address(peer) in net for net in trusted):
            hop = forwarded.split(",")[-1].strip()
            return str(ipaddress.ip_address(hop))
    except ValueError:
        pass
    return peer[:64]


def user_agent(request: Request) -> str:
    return request.headers.get("user-agent", "")[:200]


def authenticate(request: Request, auth: Auth, touch: bool = True) -> Principal:
    header = request.headers.get("authorization")
    if header is not None:
        ip = client_ip(request)
        key = _key("token-ip", ip)
        if wait := auth.throttle_wait(key):
            raise AuthError(429, "Too many failed token attempts. Try again later.", wait)
        scheme, _, raw = header.partition(" ")
        principal = auth.token(raw.strip()) if scheme.lower() == "bearer" else None
        if principal is None:
            auth.fail(key, auth.s.ip_lockout_threshold)
            auth.audit("token_use", "failure", "anonymous", ip=ip)
            raise AuthError(401, "This API token is not valid, expired or revoked.")
        return principal
    raw = request.cookies.get(SESSION_COOKIE)
    principal = auth.session(raw, touch) if raw else None
    if principal is None:
        raise AuthError(401, "Your session ended. Sign in again." if raw else "Sign in first.")
    return principal


def require(role: Role, *, session_only: bool = False, stages: tuple[Stage, ...] = ("full",)):
    """A dependency that admits callers with at least `role`, returning the Principal."""

    def dependency(request: Request, store: StoreDep) -> Principal:
        principal = authenticate(request, auth_for(request, store))
        if principal.stage not in stages:
            if principal.stage == "mfa":
                raise AuthError(401, "Enter your MFA code to finish signing in.")
            raise AuthError(403, "Set up MFA before you continue.")
        if session_only and principal.via != "session":
            raise AuthError(403, "This needs a signed-in session, not an API token.")
        if not principal.role.covers(role):
            raise AuthError(403, f"This needs the {role} role.")
        request.state.principal = principal
        return principal

    dependency.pmx_policy = Policy(role, session_only, stages)  # type: ignore[attr-defined]
    return dependency


VIEWER = require(Role.VIEWER)
ADMIN = require(Role.ADMIN)
Viewer = Annotated[Principal, Depends(VIEWER)]
Admin = Annotated[Principal, Depends(ADMIN)]
# Own account: any stage that has passed the password (enrolment must be reachable).
Account = Annotated[
    Principal, Depends(require(Role.VIEWER, session_only=True, stages=("enrol", "full")))
]
Pending = Annotated[Principal, Depends(require(Role.VIEWER, session_only=True, stages=("mfa",)))]
AnySession = Annotated[
    Principal, Depends(require(Role.VIEWER, session_only=True, stages=ALL_STAGES))
]
SignedIn = Annotated[Principal, Depends(require(Role.VIEWER, session_only=True))]
AdminSession = Annotated[Principal, Depends(require(Role.ADMIN, session_only=True))]


def set_session_cookie(response: Response, raw: str, max_age: int) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        raw,
        max_age=max_age,
        path="/",
        secure=True,
        httponly=True,
        samesite="strict",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="strict")


def _policies(dependant: Dependant) -> list[Policy]:
    found = []
    for d in dependant.dependencies:
        if (p := getattr(d.call, "pmx_policy", None)) is not None:
            found.append(p)
        found.extend(_policies(d))
    return found


def _routes(routes: list, prefix: str = "") -> Iterator[tuple[str, object]]:
    """Every route with its full path, through included routers (FastAPI keeps them lazy)."""
    for route in routes:
        if (inner := getattr(route, "original_router", None)) is not None:
            yield from _routes(inner.routes, prefix + route.include_context.prefix)
        else:
            yield prefix + getattr(route, "path", ""), route


def route_policies(app: FastAPI) -> dict[tuple[str, str], Policy | None]:
    """(method, path) -> its Policy, or None for a PUBLIC route. Raises on any gap."""
    out: dict[tuple[str, str], Policy | None] = {}
    problems = []
    for path, route in _routes(app.routes):
        if not isinstance(route, APIRoute):
            problems.append(f"{path or type(route).__name__}: not an API route (no policy)")
            continue
        policies = _policies(route.dependant)
        for method in sorted(route.methods):
            key = (method, path)
            if key in PUBLIC and policies:
                problems.append(f"{method} {path}: public and also has a role policy")
            elif key not in PUBLIC and not policies:
                problems.append(f"{method} {path}: no route policy (deny by default)")
            elif len({p.role for p in policies}) > 1:
                problems.append(f"{method} {path}: more than one role policy")
            out[key] = policies[0] if policies else None
    problems += [f"{m} {p}: in PUBLIC but no such route" for m, p in sorted(PUBLIC - set(out))]
    if problems:
        raise RuntimeError("route policy registry: " + "; ".join(problems))
    return out


check_routes = route_policies
