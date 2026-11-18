"""Secrets vault (design 7.5). See README.md and CLAUDE.md in this folder."""

from parsemaxxing.secrets.vault import (
    DEFAULT_KEK_FILE,
    KEK_ENV,
    Kek,
    Plaintext,
    SecretInfo,
    Vault,
    VaultError,
    kek_file,
    rotate_kek,
)

__all__ = [
    "DEFAULT_KEK_FILE",
    "KEK_ENV",
    "Kek",
    "Plaintext",
    "SecretInfo",
    "Vault",
    "VaultError",
    "kek_file",
    "rotate_kek",
]
