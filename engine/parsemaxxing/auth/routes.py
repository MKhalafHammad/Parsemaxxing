"""Auth API: first-run setup, login (password then MFA), logout, own account, MFA, sessions,
API tokens, users (admin) and the read-only audit log. Mounted by api/app.py."""

from typing import Annotated

from fastapi import APIRouter, Query, Request, Response
from fastapi import Path as PathParam
from pydantic import BaseModel, ConfigDict, Field, model_validator

from parsemaxxing.auth import events
from parsemaxxing.auth.model import AuthError, Principal, Role
from parsemaxxing.auth.policy import (
    SESSION_COOKIE,
    Account,
    AdminSession,
    AnySession,
    Pending,
    SignedIn,
    StoreDep,
    Viewer,
    auth_for,
    clear_session_cookie,
    client_ip,
    set_session_cookie,
    user_agent,
)
from parsemaxxing.auth.service import TOKEN_MAX_DAYS, admin_exists, public_user

router = APIRouter()
Id = Annotated[
    str, PathParam(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
]
Password = Annotated[str, Field(min_length=1, max_length=1024)]
Username = Annotated[str, Field(min_length=1, max_length=64)]


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginBody(_Body):
    username: Annotated[str, Field(min_length=1, max_length=128)]
    password: Password


class MfaBody(_Body):
    code: Annotated[str, Field(pattern=r"^\d{6}$")] | None = None
    recovery_code: Annotated[str, Field(min_length=1, max_length=64)] | None = None

    @model_validator(mode="after")
    def one(self) -> "MfaBody":
        if (self.code is None) == (self.recovery_code is None):
            raise ValueError("send code or recovery_code")
        return self


class CodeBody(_Body):
    code: Annotated[str, Field(pattern=r"^\d{6}$")]


class PasswordBody(_Body):
    password: Password


class NewPasswordBody(_Body):
    current_password: Password
    new_password: Password


class SetupBody(_Body):
    token: Annotated[str, Field(min_length=1, max_length=128)]
    username: Username
    display_name: Annotated[str, Field(max_length=128)] = ""
    password: Password


class TokenBody(_Body):
    name: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}$")]
    role: Role
    expires_in_days: Annotated[int, Field(ge=1, le=TOKEN_MAX_DAYS)] = 30


class UserBody(_Body):
    username: Username
    display_name: Annotated[str, Field(max_length=128)] = ""
    role: Role
    password: Password


class RoleBody(_Body):
    role: Role


def _me(p: Principal, user: dict) -> dict:
    return {"user": public_user(user), "stage": p.stage, "via": p.via}


def _signed_in(response: Response, auth, raw: str, stage: str, user: dict) -> dict:
    set_session_cookie(response, raw, auth.ttl(stage))
    return {"stage": stage, "user": public_user(auth.user(str(user["id"])))}


# --- first run ---------------------------------------------------------------------------


@router.get("/setup")
def setup_status(store: StoreDep) -> dict:
    return {"needed": not admin_exists(store.conn)}


@router.post("/setup", status_code=201)
def setup(body: SetupBody, request: Request, response: Response, store: StoreDep) -> dict:
    auth = auth_for(request, store)
    raw, user, stage = auth.setup(
        body.token,
        body.username,
        body.display_name,
        body.password,
        client_ip(request),
        user_agent(request),
    )
    request.app.state.setup_token_path.unlink(missing_ok=True)
    return _signed_in(response, auth, raw, stage, user)


# --- login and logout ----------------------------------------------------------------------


@router.post("/auth/login")
def login(body: LoginBody, request: Request, response: Response, store: StoreDep) -> dict:
    auth = auth_for(request, store)
    raw, user, stage = auth.login(
        body.username, body.password, client_ip(request), user_agent(request)
    )
    # Session fixation: the new id is always fresh, and any session the browser brought ends.
    auth.revoke_raw(request.cookies.get(SESSION_COOKIE, ""), "replaced at sign-in")
    return _signed_in(response, auth, raw, stage, user)


@router.post("/auth/login/mfa")
def login_mfa(
    body: MfaBody, p: Pending, request: Request, response: Response, store: StoreDep
) -> dict:
    auth = auth_for(request, store)
    raw, left = auth.login_mfa(
        p, body.code, body.recovery_code, client_ip(request), user_agent(request)
    )
    out = _signed_in(response, auth, raw, "full", {"id": p.user_id})
    if left is not None:
        out["recovery_codes_left"] = left
    return out


@router.post("/auth/logout")
def logout(request: Request, response: Response, store: StoreDep) -> dict:
    auth = auth_for(request, store)
    p = auth.session(request.cookies.get(SESSION_COOKIE, ""))
    if p is not None:
        auth.revoke_session(p.credential_id, "signed out")
        auth.audit("logout", "success", p.username, p.user_id, client_ip(request))
    clear_session_cookie(response)
    return {"signed_out": True}


@router.get("/auth/me")
def me(p: AnySession, request: Request, store: StoreDep) -> dict:
    return _me(p, auth_for(request, store).user(p.user_id))


# --- own account -------------------------------------------------------------------------


@router.post("/auth/password")
def change_password(
    body: NewPasswordBody, p: SignedIn, request: Request, response: Response, store: StoreDep
) -> dict:
    auth, ip = auth_for(request, store), client_ip(request)
    auth.change_password(p, body.current_password, body.new_password, ip)
    raw = auth.reissue(p, "password change", ip, user_agent(request))
    return _signed_in(response, auth, raw, "full", {"id": p.user_id})


@router.post("/auth/mfa/enrol")
def mfa_enrol(p: Account, request: Request, store: StoreDep) -> dict:
    return auth_for(request, store).mfa_enrol(p, client_ip(request))


@router.post("/auth/mfa/confirm")
def mfa_confirm(
    body: CodeBody, p: Account, request: Request, response: Response, store: StoreDep
) -> dict:
    auth, ip = auth_for(request, store), client_ip(request)
    codes = auth.mfa_confirm(p, body.code, ip)
    raw = auth.reissue(p, "mfa change", ip, user_agent(request))
    return _signed_in(response, auth, raw, "full", {"id": p.user_id}) | {"recovery_codes": codes}


@router.post("/auth/mfa/disable")
def mfa_disable(
    body: PasswordBody, p: SignedIn, request: Request, response: Response, store: StoreDep
) -> dict:
    auth, ip = auth_for(request, store), client_ip(request)
    auth.mfa_disable(p, body.password, ip)
    raw = auth.reissue(p, "mfa change", ip, user_agent(request))
    return _signed_in(response, auth, raw, "full", {"id": p.user_id})


@router.post("/auth/mfa/recovery-codes")
def recovery_codes(body: PasswordBody, p: SignedIn, request: Request, store: StoreDep) -> dict:
    codes = auth_for(request, store).regenerate_codes(p, body.password, client_ip(request))
    return {"recovery_codes": codes}


@router.get("/auth/sessions")
def sessions(p: SignedIn, request: Request, store: StoreDep) -> list[dict]:
    return [
        {
            "id": str(s["id"]),
            "created_at": str(s["created_at"]),
            "last_seen_at": str(s["last_seen_at"]),
            "expires_at": str(s["expires_at"]),
            "ip": s["ip"],
            "user_agent": s["user_agent"],
            "current": str(s["id"]) == p.credential_id,
        }
        for s in auth_for(request, store).sessions(p.user_id)
    ]


@router.post("/auth/sessions/{session_id}/revoke")
def revoke_session(
    session_id: Id, p: SignedIn, request: Request, response: Response, store: StoreDep
) -> dict:
    auth = auth_for(request, store)
    if not any(str(s["id"]) == session_id for s in auth.sessions(p.user_id)):
        raise AuthError(404, "no such session")  # another user's session looks missing
    auth.revoke_session(session_id, "revoked by its user")
    auth.audit("session_revoke", "success", p.username, p.user_id, client_ip(request))
    if session_id == p.credential_id:
        clear_session_cookie(response)
    return {"revoked": True}


@router.post("/auth/sessions/revoke-all")
def sign_out_everywhere(p: SignedIn, request: Request, response: Response, store: StoreDep) -> dict:
    auth = auth_for(request, store)
    n = auth.revoke_all(p.user_id, "signed out everywhere")
    auth.audit("session_revoke", "success", p.username, p.user_id, client_ip(request), all=True)
    clear_session_cookie(response)
    return {"revoked": n}


# --- API tokens --------------------------------------------------------------------------


def _token(t: dict) -> dict:
    status = "revoked" if t["revoked_at"] else "expired" if t["expired"] else "active"
    return {
        "id": str(t["id"]),
        "name": t["name"],
        "role": t["role"],
        "owner": t["owner"],
        "created_at": str(t["created_at"]),
        "expires_at": str(t["expires_at"]),
        "last_used_at": str(t["last_used_at"]) if t["last_used_at"] else None,
        "status": status,
    }


@router.get("/auth/tokens")
def tokens(p: SignedIn, request: Request, store: StoreDep) -> list[dict]:
    """Admins see every token; everyone else their own."""
    return [_token(t) for t in auth_for(request, store).tokens(p)]


@router.post("/auth/tokens", status_code=201)
def create_token(body: TokenBody, p: SignedIn, request: Request, store: StoreDep) -> dict:
    # Viewers may create viewer tokens for themselves (UX-Q1); a token never outranks you,
    # and tokens cannot mint tokens (session only).
    raw, row = auth_for(request, store).create_token(
        p, body.name, body.role, body.expires_in_days, client_ip(request)
    )
    return {
        "token": raw,  # shown once; only its SHA-256 is stored
        "id": str(row["id"]),
        "name": row["name"],
        "role": row["role"],
        "expires_at": str(row["expires_at"]),
    }


@router.post("/auth/tokens/{token_id}/revoke")
def revoke_token(token_id: Id, p: SignedIn, request: Request, store: StoreDep) -> dict:
    auth_for(request, store).revoke_token(p, token_id, client_ip(request))
    return {"revoked": True}


# --- users (admin) -----------------------------------------------------------------------


@router.get("/auth/users")
def users(p: AdminSession, request: Request, store: StoreDep) -> list[dict]:
    return [public_user(u) for u in auth_for(request, store).users()]


@router.post("/auth/users", status_code=201)
def create_user(body: UserBody, p: AdminSession, request: Request, store: StoreDep) -> dict:
    auth = auth_for(request, store)
    row = auth.create_user(
        p, body.username, body.display_name, body.role, body.password, client_ip(request)
    )
    return public_user(auth.user(str(row["id"])))


@router.post("/auth/users/{user_id}/role")
def set_role(
    user_id: Id, body: RoleBody, p: AdminSession, request: Request, store: StoreDep
) -> dict:
    return public_user(auth_for(request, store).set_role(p, user_id, body.role, client_ip(request)))


@router.post("/auth/users/{user_id}/disable")
def disable_user(user_id: Id, p: AdminSession, request: Request, store: StoreDep) -> dict:
    auth = auth_for(request, store)
    return public_user(auth.set_disabled(p, user_id, True, client_ip(request)))


@router.post("/auth/users/{user_id}/enable")
def enable_user(user_id: Id, p: AdminSession, request: Request, store: StoreDep) -> dict:
    auth = auth_for(request, store)
    return public_user(auth.set_disabled(p, user_id, False, client_ip(request)))


@router.post("/auth/users/{user_id}/sessions/revoke")
def sign_user_out(user_id: Id, p: AdminSession, request: Request, store: StoreDep) -> dict:
    auth = auth_for(request, store)
    auth.user(user_id)  # 404 for an unknown id
    n = auth.revoke_all(user_id, "revoked by an admin")
    auth.audit("session_revoke", "success", p.username, user_id, client_ip(request), all=True)
    return {"revoked": n}


# --- audit log (read-only for everyone; nobody can edit it) ------------------------------


@router.get("/audit")
def audit_log(
    p: Viewer,
    store: StoreDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    before: Annotated[int | None, Query(ge=1)] = None,
    event: Annotated[str | None, Query(pattern=r"^[a-z][a-z_]{1,40}$")] = None,
) -> list[dict]:
    return [
        {
            "id": e["id"],
            "at": str(e["at"]),
            "actor": e["actor"],
            "user_id": str(e["user_id"]) if e["user_id"] else None,
            "event": e["event"],
            "outcome": e["outcome"],
            "ip": e["ip"],
            "detail": e["detail"],
        }
        for e in events.recent(store.conn, limit, before, event)
    ]
