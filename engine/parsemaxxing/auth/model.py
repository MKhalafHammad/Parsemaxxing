"""Roles, the authenticated principal and the one auth error type (design 7.3, D6)."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal


class Role(StrEnum):
    VIEWER = "viewer"  # sees everything except secret values, changes nothing
    ADMIN = "admin"  # operates the platform

    def covers(self, other: "Role") -> bool:
        return _RANK[self] >= _RANK[other]

    @staticmethod
    def lower(a: "Role", b: "Role") -> "Role":
        return a if _RANK[a] <= _RANK[b] else b


_RANK = {Role.VIEWER: 1, Role.ADMIN: 2}
Stage = Literal["mfa", "enrol", "full"]
ALL_STAGES: tuple[Stage, ...] = ("mfa", "enrol", "full")


@dataclass(frozen=True)
class Principal:
    """Who is calling. `credential_id` is the session's or token's public id, never its value."""

    user_id: str
    username: str
    role: Role
    via: Literal["session", "token"]
    stage: Stage
    credential_id: str


class AuthError(Exception):
    """A refused auth request. `message` is written for the user: never a password, token,
    code or whether an account exists."""

    def __init__(self, status: int, message: str, retry_after: int = 0):
        super().__init__(message)
        self.status, self.message, self.retry_after = status, message, retry_after
        self.pad_until = 0.0  # monotonic time a failed sign-in is held until (auth.service)
