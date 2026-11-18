"""Authentication and authorization (design 7.3). See README.md and CLAUDE.md in this folder."""

from parsemaxxing.auth.model import AuthError, Principal, Role
from parsemaxxing.auth.policy import PUBLIC, SESSION_COOKIE, check_routes, require

__all__ = ["PUBLIC", "SESSION_COOKIE", "AuthError", "Principal", "Role", "check_routes", "require"]
