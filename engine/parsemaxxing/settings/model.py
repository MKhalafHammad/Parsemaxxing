"""Scopes, the setting-group base class and the field helper (design 7.5)."""

import re
from dataclasses import dataclass
from typing import Annotated, Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Level = Literal["platform", "environment", "client"]
LEVELS: tuple[Level, ...] = ("platform", "environment", "client")
NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,62}")
GROUP_NAME = re.compile(r"[a-z][a-z0-9_]{0,62}")
ENV_NAME = re.compile(r"[A-Z][A-Z0-9_]{0,127}")
# A setting that names a secret holds the vault id (a UUID), never the value.
SecretRef = Annotated[
    str,
    StringConstraints(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"),
]


class SettingsError(ValueError):
    """A refused read or write. Messages name fields and variables, never values of secrets."""


@dataclass(frozen=True)
class Scope:
    """Where a setting or secret lives. There is no implicit current scope: pass one."""

    environment: str = ""
    client: str = ""

    def __post_init__(self) -> None:
        for part in (self.environment, self.client):
            if part and not NAME.fullmatch(part):
                raise SettingsError("scope names match [a-z0-9][a-z0-9_-]{0,62}")
        if self.client and not self.environment:
            raise SettingsError("a client scope needs its environment")

    @property
    def level(self) -> Level:
        return "client" if self.client else "environment" if self.environment else "platform"

    def layers(self) -> list["Scope"]:
        """This scope and every scope above it, platform first."""
        out = [PLATFORM]
        if self.environment:
            out.append(Scope(self.environment))
        if self.client:
            out.append(self)
        return out


PLATFORM = Scope()


def setting(
    default: Any = None,
    *,
    scopes: tuple[Level, ...] = ("platform",),
    env: str | None = None,
    secret: bool = False,
    **field: Any,
) -> Any:
    """A setting field. `scopes`: the levels where it may be set (a lower level may override only
    if listed). `env`: a variable that, when present, overrides it everywhere and makes it read-only
    ("managed by environment"). `secret`: the field holds a vault id (type `SecretRef | None`);
    its `env` variable, when set and non-empty, overrides the vault value at runtime (bootstrap
    reads it; the settings service only reports the source and never reads the value)."""
    return Field(
        default,
        json_schema_extra={"pmx": {"scopes": scopes, "env": env, "secret": secret}},
        **field,
    )


class SettingsGroup(BaseModel):
    """One group of settings. Subclasses set GROUP and VERSION and use `setting()` for fields."""

    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)
    GROUP: ClassVar[str]
    VERSION: ClassVar[int] = 1
    registry: ClassVar[dict[str, type["SettingsGroup"]]] = {}

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        super().__pydantic_init_subclass__(**kwargs)
        if not GROUP_NAME.fullmatch(cls.GROUP) or cls.GROUP == "vault":
            raise TypeError(f"{cls.__name__}: bad GROUP {cls.GROUP!r}")
        if cls.registry.get(cls.GROUP, cls) is not cls:
            raise TypeError(f"settings group {cls.GROUP!r} defined twice")
        for name in cls.model_fields:
            meta = cls.meta(name)
            if not meta["scopes"] or set(meta["scopes"]) - set(LEVELS):
                raise TypeError(f"{cls.__name__}.{name}: scopes must be among {LEVELS}")
            if meta["env"] and not ENV_NAME.fullmatch(meta["env"]):
                raise TypeError(f"{cls.__name__}.{name}: bad env override")
        cls.registry[cls.GROUP] = cls

    @classmethod
    def meta(cls, name: str) -> dict:
        extra = cls.model_fields[name].json_schema_extra
        if not isinstance(extra, dict) or "pmx" not in extra:
            raise TypeError(f"{cls.__name__}.{name}: declare it with setting()")
        return extra["pmx"]  # type: ignore[return-value]

    @classmethod
    def secret_fields(cls) -> set[str]:
        return {n for n in cls.model_fields if cls.meta(n)["secret"]}
