"""Password hashing and the password rule (design 7.3): Argon2id, 12 to 128 characters, not on
the common-password list, no composition rules."""

import secrets
from functools import cache
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from argon2.profiles import RFC_9106_LOW_MEMORY

# RFC 9106 low-memory profile: Argon2id, m=64 MiB, t=3, p=4, above the OWASP Password Storage
# Cheat Sheet minimum (m=19 MiB, t=2, p=1). Raising it makes old hashes rehash at next login.
HASHER = PasswordHasher.from_parameters(RFC_9106_LOW_MEMORY)
MIN_LENGTH, MAX_LENGTH = 12, 128
LIST = Path(__file__).with_name("common_passwords.txt")


class PasswordRefused(ValueError):
    """The password breaks the rule. The message is for the user and never quotes it."""


@cache
def _common() -> frozenset[str]:
    lines = LIST.read_text(encoding="utf-8").splitlines()
    return frozenset(ln.strip().lower() for ln in lines if ln.strip() and not ln.startswith("#"))


@cache
def _dummy() -> str:
    # Verified for unknown or password-less accounts, so they take as long as a wrong password.
    return HASHER.hash(secrets.token_urlsafe(32))


def check(password: str, username: str = "") -> None:
    if not MIN_LENGTH <= len(password) <= MAX_LENGTH:
        raise PasswordRefused(f"Use a password of {MIN_LENGTH} to {MAX_LENGTH} characters.")
    lowered = password.lower()
    if lowered in _common():
        raise PasswordRefused("This password is on the list of common passwords. Pick another.")
    if len(username) >= 4 and username.lower() in lowered:
        raise PasswordRefused("The password must not contain your user name.")


def hash_password(password: str) -> str:
    return HASHER.hash(password)


def verify(stored: str | None, password: str) -> bool:
    """Constant work whether or not the account exists (argon2 compares in constant time)."""
    try:
        return HASHER.verify(stored or _dummy(), password) and stored is not None
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(stored: str) -> bool:
    return HASHER.check_needs_rehash(stored)
