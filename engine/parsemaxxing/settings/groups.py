"""The setting groups. Variable names are v1's: a v1 `.env` shows as "managed by environment".

Secret fields hold vault ids. Their variables (LLM_API_KEY, SPLUNK_*_TOKEN) are read-only
overrides like any other: set and non-empty, the variable's value is used at runtime instead of
the vault (the settings service never reads the value, it only reports the source).
"""

import ipaddress
import re
from typing import Annotated, Literal
from urllib.parse import urlsplit

from ldap3.core.exceptions import LDAPInvalidDnError
from ldap3.utils.dn import parse_dn
from pydantic import (
    AfterValidator,
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    StringConstraints,
    field_validator,
    model_validator,
)

from parsemaxxing.settings.model import SecretRef, SettingsGroup, setting


def _no_userinfo(url: AnyHttpUrl) -> AnyHttpUrl:
    # Credentials belong in the vault; a user:pass@ URL would store and show one in clear.
    if url.username or url.password:
        raise ValueError("a URL must not contain a user name or password")
    return url


Url = Annotated[AnyHttpUrl, AfterValidator(_no_userinfo)]  # every URL setting uses this


class LlmSettings(SettingsGroup):
    GROUP = "llm"
    VERSION = 1
    base_url: Url | None = setting(None, env="LLM_BASE_URL")
    model: str | None = setting(None, env="LLM_MODEL", min_length=1, max_length=200)
    api_key: SecretRef | None = setting(None, env="LLM_API_KEY", secret=True)
    run_token_ceiling: int = setting(
        300_000, env="PARSEMAXXING_RUN_TOKEN_CEILING", ge=1_000, le=10_000_000
    )


class SplunkSettings(SettingsGroup):
    GROUP = "splunk"
    VERSION = 1
    host: str | None = setting(
        None,
        scopes=("environment",),
        env="SPLUNK_HOST",
        min_length=1,
        max_length=253,
        pattern=r"^[A-Za-z0-9.:-]+$",
    )
    port: int = setting(8089, scopes=("platform", "environment"), env="SPLUNK_PORT", ge=1, le=65535)
    search_token: SecretRef | None = setting(
        None, scopes=("environment",), env="SPLUNK_SEARCH_TOKEN", secret=True
    )
    deploy_token: SecretRef | None = setting(
        None, scopes=("environment",), env="SPLUNK_DEPLOY_TOKEN", secret=True
    )
    test_index: str = setting(
        "pmx_test",
        scopes=("platform", "environment", "client"),
        env="PARSEMAXXING_TEST_INDEX",
        pattern=r"^pmx_[a-z0-9_]{1,60}$",
    )


class IngestSettings(SettingsGroup):
    GROUP = "ingest"
    VERSION = 1
    job_ingest_mb: float = setting(20, env="PARSEMAXXING_JOB_INGEST_MB", gt=0, le=1_000)
    daily_ingest_mb: float = setting(500, env="PARSEMAXXING_DAILY_INGEST_MB", gt=0, le=100_000)


class RunSettings(SettingsGroup):
    """Worker tunables (were constants in orchestrator/worker.py and run.py)."""

    GROUP = "run"
    VERSION = 1
    daily_token_budget: int = setting(2_000_000, ge=1_000, le=1_000_000_000)
    llm_slots: int = setting(2, ge=1, le=64)  # model calls at once, across every worker
    max_attempts: int = setting(5, ge=1, le=20)  # attempts per stage


class BackupSettings(SettingsGroup):
    GROUP = "backup"
    VERSION = 1
    # The age public key backups are encrypted to; its private key is never on the server.
    age_recipient: str | None = setting(
        None, env="PARSEMAXXING_BACKUP_RECIPIENT", pattern=r"^age1[02-9ac-hj-np-z]{58}$"
    )


class AuthSettings(SettingsGroup):
    """Local accounts, sessions and lockout (design 7.3). Platform scope only."""

    GROUP = "auth"
    VERSION = 1
    require_mfa_admins: bool = setting(True)
    idle_timeout_minutes: int = setting(30, ge=5, le=1440)
    absolute_timeout_hours: int = setting(12, ge=1, le=168)
    # Lockout: after `lockout_threshold` failures for one user name (or `ip_lockout_threshold`
    # from one client IP), wait base * 2^(failures - threshold) seconds, at most the maximum.
    lockout_threshold: int = setting(5, ge=3, le=20)
    ip_lockout_threshold: int = setting(20, ge=5, le=1000)
    lockout_base_seconds: int = setting(60, ge=1, le=3600)
    lockout_max_seconds: int = setting(900, ge=60, le=86400)
    # Every failed sign-in (local or directory) is held until this long after it started, so
    # which step failed, or whether a name is local, does not show in the timing.
    failure_min_seconds: float = setting(1.0, ge=0, le=5)


_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_DNS_NAME = re.compile(
    r"(?=.{1,253}$)[A-Za-z0-9]([A-Za-z0-9-]{0,62})(\.[A-Za-z0-9]([A-Za-z0-9-]{0,62}))*"
)


def _dn(value: str) -> str:
    """A DN typed by an admin: one line, and one ldap3 can parse (RFC 4514)."""
    if _CONTROL.search(value):
        raise ValueError("a DN must be one line without control characters")
    try:
        parse_dn(value)
    except LDAPInvalidDnError:
        raise ValueError(
            "not a valid DN, e.g. cn=Parsemaxxing,ou=Groups,dc=acme,dc=example"
        ) from None
    return value


Dn = Annotated[str, StringConstraints(min_length=3, max_length=1024), AfterValidator(_dn)]
Attribute = Annotated[str, StringConstraints(pattern=r"^[A-Za-z][A-Za-z0-9-]{0,63}$")]


class LdapServer(BaseModel):
    """One directory server: `ldaps://host[:636]`, or `ldap://host[:389]` with StartTLS.
    Plain LDAP (ldap:// without StartTLS) is refused here and again at connect."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    url: Annotated[str, StringConstraints(min_length=8, max_length=300)]
    start_tls: bool = False

    @model_validator(mode="after")
    def _secure(self) -> "LdapServer":
        u = urlsplit(self.url)
        if u.scheme not in ("ldaps", "ldap"):
            raise ValueError("a server URL starts with ldaps:// (or ldap:// with StartTLS)")
        if u.scheme == "ldap" and not self.start_tls:
            raise ValueError("plain LDAP is refused: use ldaps:// or turn on StartTLS")
        if u.scheme == "ldaps" and self.start_tls:
            raise ValueError("ldaps:// is already TLS: turn StartTLS off")
        if u.username or u.password or u.path not in ("", "/") or u.query or u.fragment:
            raise ValueError("a server URL is only ldaps://host[:port]")
        try:
            u.port  # noqa: B018 - raises on a bad port
        except ValueError:
            raise ValueError("bad port in the server URL") from None
        if not _host_ok(u.hostname or ""):
            raise ValueError("a server URL needs a host name or IP address")
        return self

    @property
    def host(self) -> str:
        return urlsplit(self.url).hostname or ""

    @property
    def port(self) -> int:
        u = urlsplit(self.url)
        return u.port or (636 if u.scheme == "ldaps" else 389)

    @property
    def ldaps(self) -> bool:
        return urlsplit(self.url).scheme == "ldaps"


def _host_ok(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return bool(_DNS_NAME.fullmatch(host))


class LdapSettings(SettingsGroup):
    """Directory sign-in (design 7.4). Platform scope only. The bind password and the CA bundle
    (PEM: not secret, but integrity-protected) live in the vault; these fields hold their ids.
    `missing_for_enable` lists what must be set before `enabled` may be turned on."""

    GROUP = "ldap"
    VERSION = 1
    enabled: bool = setting(False)
    servers: list[LdapServer] = setting([], max_length=10)  # tried in order (failover)
    ca_bundle: SecretRef | None = setting(None, secret=True)  # set through its own route
    bind_dn: Dn | None = setting(None)
    bind_password: SecretRef | None = setting(None, secret=True)
    user_search_base: Dn | None = setting(None)
    # `{username}` (for example `(|(uid={username})(mail={username}))`), each one filled with
    # the RFC 4515-escaped user name.
    user_filter: str = setting("(uid={username})", min_length=12, max_length=512)
    username_attribute: Attribute = setting("uid")  # uid, sAMAccountName, userPrincipalName
    display_name_attribute: Attribute = setting("displayName")
    # member_of: the user's memberOf values; member: groups under group_search_base whose
    # `member` holds the user's DN (nested_groups also follows groups inside groups);
    # ad_nested: Active Directory's LDAP_MATCHING_RULE_IN_CHAIN under group_search_base.
    group_mode: Literal["member_of", "member", "ad_nested"] = setting("member_of")
    group_search_base: Dn | None = setting(None)
    nested_groups: bool = setting(False)
    # Group DN -> role; the highest mapped role wins and no mapped group means no access.
    group_roles: dict[Dn, Literal["viewer", "admin"]] = setting({}, max_length=200)
    connect_timeout_seconds: int = setting(5, ge=1, le=60)
    read_timeout_seconds: int = setting(10, ge=1, le=120)
    page_size: int = setting(500, ge=1, le=5000)
    # TOTP enrolment is always open to directory users; this makes it required at sign-in.
    require_mfa: bool = setting(False)
    # Directory users' sessions end after at most this long (also capped by the auth group's
    # absolute timeout), so a removal from a group takes effect within it.
    session_max_hours: int = setting(12, ge=1, le=24)

    @field_validator("user_filter")
    @classmethod
    def _filter(cls, v: str) -> str:
        rest = v.replace("{username}", "")
        if _CONTROL.search(v) or "{" in rest or "}" in rest or not 1 <= v.count("{username}") <= 4:
            raise ValueError(
                "the filter is one line with {username} (1 to 4 times), no other braces"
            )
        depth, closed_at = 0, []
        for i, c in enumerate(v):
            depth += {"(": 1, ")": -1}.get(c, 0)
            if depth <= 0:
                closed_at.append(i)
        # one filter: the opening "(" closes exactly at the last character
        if not v.startswith("(") or closed_at != [len(v) - 1] or depth != 0:
            raise ValueError("the filter must be one parenthesised LDAP filter")
        return v

    def missing_for_enable(self) -> list[str]:
        need = ["servers", "ca_bundle", "bind_dn", "bind_password", "user_search_base"]
        if self.group_mode != "member_of":
            need.append("group_search_base")
        need.append("group_roles")
        return [n for n in need if not getattr(self, n)]
