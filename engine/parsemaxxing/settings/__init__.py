"""Settings service (design 7.5). See README.md for the interface."""

from parsemaxxing.settings.groups import (
    AuthSettings,
    BackupSettings,
    IngestSettings,
    LlmSettings,
    RunSettings,
    SplunkSettings,
)
from parsemaxxing.settings.model import (
    PLATFORM,
    Scope,
    SecretRef,
    SettingsError,
    SettingsGroup,
    setting,
)
from parsemaxxing.settings.service import Change, ConflictError, Effective, SettingsService

__all__ = [
    "PLATFORM",
    "AuthSettings",
    "BackupSettings",
    "Change",
    "ConflictError",
    "Effective",
    "IngestSettings",
    "LlmSettings",
    "RunSettings",
    "Scope",
    "SecretRef",
    "SettingsError",
    "SettingsGroup",
    "SettingsService",
    "SplunkSettings",
    "setting",
]
