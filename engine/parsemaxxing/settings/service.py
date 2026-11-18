"""The settings service (design 7.5): resolve, change, history, snapshots, export and import.

Resolution per field, lowest wins: default < platform < environment < client < environment
variable. A stored value counts only at a level the field lists in `scopes`. A secret field's
variable (set and non-empty) is reported as the source but its value is never read here: the
vault id stays the resolved value and bootstrap uses the variable instead of the vault.
"""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, TypeVar

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from parsemaxxing.settings.model import Scope, SettingsError, SettingsGroup

G = TypeVar("G", bound=SettingsGroup)
Source = Literal["default", "platform", "environment", "client", "environment variable"]
EXPORT_FORMAT = "parsemaxxing-settings/1"


@dataclass(frozen=True)
class Effective:
    """A field's effective value and where it comes from. Secret fields show only whether set."""

    value: Any
    source: Source
    read_only: bool  # managed by an environment variable
    secret: bool


@dataclass(frozen=True)
class Change:
    group: str
    field: str
    old: Any  # None when not set at this scope; secret fields never appear
    new: Any


class _GroupExport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)
    values: dict[str, Any]


class ExportDoc(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format: Literal["parsemaxxing-settings/1"]
    scope: dict[str, str]
    groups: dict[str, _GroupExport]


class ConflictError(SettingsError):
    """The group changed since the version the caller read."""


class SettingsService:
    """`environ` is the process environment, passed in by bootstrap (this module never reads
    os.environ). `conn` is an autocommit psycopg connection with dict rows (ledger.store)."""

    def __init__(self, conn: psycopg.Connection, environ: Mapping[str, str]):
        self.conn = conn
        self.environ = dict(environ)

    # --- reads ---------------------------------------------------------------------------

    def get(self, group: type[G], scope: Scope) -> G:
        """The effective, validated, frozen settings of a group at a scope."""
        return self._resolve(group, scope)[0]

    def explain(self, group: type[SettingsGroup], scope: Scope) -> dict[str, Effective]:
        model, sources = self._resolve(group, scope)
        out = {}
        for name in group.model_fields:
            secret = name in group.secret_fields()
            value = getattr(model, name)
            out[name] = Effective(
                value=(value is not None or sources[name] == "environment variable")
                if secret
                else model.model_dump(mode="json")[name],
                source=sources[name],
                read_only=sources[name] == "environment variable",
                secret=secret,
            )
        return out

    def stored(self, group: type[SettingsGroup], scope: Scope) -> tuple[dict, int]:
        """The values set exactly at this scope and the row's version (0: no row)."""
        row = self.conn.execute(
            "SELECT version, schema_version, value FROM settings_groups"
            " WHERE environment = %s AND client = %s AND grp = %s",
            (scope.environment, scope.client, group.GROUP),
        ).fetchone()
        if row is None:
            return {}, 0
        if row["schema_version"] > group.VERSION:  # written by a newer engine: do not guess
            raise SettingsError(
                f"group {group.GROUP} is stored as version "
                f"{row['schema_version']}, this engine knows {group.VERSION}"
            )
        # shortcut: older schema versions are read as-is; a version that renames or removes a
        # field needs an upgrade step here.
        return dict(row["value"]), int(row["version"])

    def history(
        self, scope: Scope | None = None, group: str | None = None, limit: int = 100
    ) -> list[dict]:
        """Newest first; filtered to one scope and/or group when given."""
        env, client = (scope.environment, scope.client) if scope else (None, None)
        return self.conn.execute(
            "SELECT id, at, actor, environment, client, grp, field, action, old_value, new_value,"
            " redacted FROM settings_history"
            " WHERE (%(env)s::text IS NULL OR (environment = %(env)s AND client = %(client)s))"
            " AND (%(grp)s::text IS NULL OR grp = %(grp)s) ORDER BY id DESC LIMIT %(limit)s",
            {"env": env, "client": client, "grp": group, "limit": min(max(limit, 1), 1000)},
        ).fetchall()

    # --- writes --------------------------------------------------------------------------

    def set(
        self,
        group: type[SettingsGroup],
        scope: Scope,
        values: Mapping[str, Any],
        actor: str,
        *,
        unset: tuple[str, ...] = (),
        expected_version: int | None = None,
    ) -> int:
        """Set fields at `scope` and reset `unset` ones to inherited. Returns the new version."""
        with self.conn.transaction():
            old, version, new = self._prepare(group, scope, values, unset)
            if expected_version is not None and expected_version != version:
                raise ConflictError(f"group {group.GROUP} changed (version {version})")
            if new == old:
                return version
            if version == 0:
                cur = self.conn.execute(
                    "INSERT INTO settings_groups (environment, client, grp, version,"
                    " schema_version, value, updated_by) VALUES (%s, %s, %s, 1, %s, %s, %s)"
                    " ON CONFLICT DO NOTHING",
                    (
                        scope.environment,
                        scope.client,
                        group.GROUP,
                        group.VERSION,
                        Jsonb(new),
                        actor,
                    ),
                )
            else:
                cur = self.conn.execute(
                    "UPDATE settings_groups SET version = version + 1, schema_version = %s,"
                    " value = %s, updated_by = %s, updated_at = now()"
                    " WHERE environment = %s AND client = %s AND grp = %s AND version = %s",
                    (
                        group.VERSION,
                        Jsonb(new),
                        actor,
                        scope.environment,
                        scope.client,
                        group.GROUP,
                        version,
                    ),
                )
            if cur.rowcount != 1:
                raise ConflictError(f"group {group.GROUP} changed concurrently")
            secrets = group.secret_fields()
            for name in sorted(set(old) | set(new)):
                if old.get(name, _MISSING) == new.get(name, _MISSING):
                    continue
                redacted = name in secrets
                self.conn.execute(
                    "INSERT INTO settings_history (actor, environment, client, grp, field,"
                    " action, old_value, new_value, redacted) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        actor,
                        scope.environment,
                        scope.client,
                        group.GROUP,
                        name,
                        "set" if name in new else "reset",
                        None if redacted or name not in old else Jsonb(old[name]),
                        None if redacted or name not in new else Jsonb(new[name]),
                        redacted,
                    ),
                )
            return version + 1

    # --- snapshots -----------------------------------------------------------------------

    def snapshot(self, scope: Scope) -> str:
        """Store the effective settings of every group at `scope`; return their SHA-256."""
        body = {
            "scope": {"environment": scope.environment, "client": scope.client},
            "groups": {
                name: {
                    "version": cls.VERSION,
                    "values": self.get(cls, scope).model_dump(mode="json"),
                }
                for name, cls in sorted(SettingsGroup.registry.items())
            },
        }
        digest = hashlib.sha256(_canonical(body)).hexdigest()
        self.conn.execute(
            "INSERT INTO settings_snapshots (hash, body) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (digest, Jsonb(body)),
        )
        return digest

    def load_snapshot(self, digest: str) -> dict[str, SettingsGroup]:
        """The groups of a snapshot, after checking the stored body still has that hash."""
        row = self.conn.execute(
            "SELECT body FROM settings_snapshots WHERE hash = %s", (digest,)
        ).fetchone()
        if row is None or hashlib.sha256(_canonical(row["body"])).hexdigest() != digest:
            raise SettingsError(f"settings snapshot {digest[:12]} is missing or altered")
        out = {}
        for name, g in row["body"]["groups"].items():
            cls = SettingsGroup.registry.get(name)
            if cls is None or g["version"] > cls.VERSION:
                raise SettingsError(f"settings snapshot {digest[:12]}: unknown group {name}")
            out[name] = cls.model_validate(g["values"])
        return out

    # --- export and import ---------------------------------------------------------------

    def export(self, scope: Scope) -> dict:
        """The non-secret values set exactly at `scope`, as JSON. Never contains secret fields."""
        groups = {}
        for name, cls in sorted(SettingsGroup.registry.items()):
            values, _ = self.stored(cls, scope)
            values = {k: v for k, v in values.items() if k not in cls.secret_fields()}
            if values:
                groups[name] = {"version": cls.VERSION, "values": values}
        return {
            "format": EXPORT_FORMAT,
            "scope": {"environment": scope.environment, "client": scope.client},
            "groups": groups,
        }

    def plan_import(self, doc: Any, scope: Scope) -> list[Change]:
        """Validate an export against `scope` (any scope: this is also "clone") and diff it.
        Groups in the document replace their non-secret values at `scope`; secrets stay."""
        changes = []
        for cls, values, unset in self._import_steps(doc):
            old, _, new = self._prepare(cls, scope, values, unset)
            for name in sorted(set(old) | set(new)):
                if old.get(name) != new.get(name) or (name in old) != (name in new):
                    changes.append(Change(cls.GROUP, name, old.get(name), new.get(name)))
        return changes

    def apply_import(self, doc: Any, scope: Scope, actor: str) -> list[Change]:
        """plan_import, then apply every group in one transaction (recorded in history)."""
        with self.conn.transaction():
            changes = self.plan_import(doc, scope)
            for cls, values, unset in self._import_steps(doc):
                self.set(cls, scope, values, actor, unset=unset)
        return changes

    # --- internals -----------------------------------------------------------------------

    def _import_steps(self, doc: Any) -> list[tuple[type[SettingsGroup], dict, tuple[str, ...]]]:
        try:
            parsed = ExportDoc.model_validate(doc)
        except ValidationError as e:
            raise SettingsError(f"not a settings export: {e.error_count()} errors") from None
        steps = []
        for name, g in sorted(parsed.groups.items()):
            cls = SettingsGroup.registry.get(name)
            if cls is None:
                raise SettingsError(f"unknown settings group {name}")
            if g.version > cls.VERSION:
                raise SettingsError(f"group {name} version {g.version} is newer than this engine")
            if bad := set(g.values) & cls.secret_fields():
                raise SettingsError(f"an import never carries secrets: {sorted(bad)}")
            unset = tuple(
                n for n in cls.model_fields if n not in g.values and n not in cls.secret_fields()
            )
            steps.append((cls, g.values, unset))
        return steps

    def _prepare(
        self,
        group: type[SettingsGroup],
        scope: Scope,
        values: Mapping[str, Any],
        unset: tuple[str, ...],
    ) -> tuple[dict, int, dict]:
        """Check a change and return (old stored, version, new stored). Nothing is written."""
        old, version = self.stored(group, scope)
        new = dict(old)
        for name in [*values, *unset]:
            if name not in group.model_fields:
                raise SettingsError(f"{group.GROUP} has no setting {name}")
            meta = group.meta(name)
            if scope.level not in meta["scopes"]:
                raise SettingsError(f"{group.GROUP}.{name} cannot be set for a {scope.level}")
            if self._env_active(group, name):
                changes = (
                    (name in old) if name in unset else values[name] != old.get(name, _MISSING)
                )
                if changes:
                    raise SettingsError(
                        f"{group.GROUP}.{name} is managed by environment variable {meta['env']}"
                    )
        for name in unset:
            new.pop(name, None)
        for name, value in values.items():
            if name in group.secret_fields() and value is not None:
                self._check_secret(scope, value, f"{group.GROUP}.{name}")
            new[name] = value
        # This scope must validate; a lower scope's own row is validated whenever it is read.
        self._resolve(group, scope, override=new)
        return old, version, _normalize(group, new)

    def _check_secret(self, scope: Scope, secret_id: Any, where: str) -> None:
        """A secret field may name only a secret of exactly this scope."""
        try:
            row = self.conn.execute(
                "SELECT 1 FROM secrets WHERE id = %s AND environment = %s AND client = %s",
                (str(secret_id), scope.environment, scope.client),
            ).fetchone()
        except psycopg.errors.InvalidTextRepresentation:
            row = None
        if row is None:
            raise SettingsError(f"{where}: no such secret in this scope")

    def _env_active(self, group: type[SettingsGroup], name: str) -> bool:
        """A variable overrides the field: present (plain fields) or non-empty (secrets)."""
        var = group.meta(name)["env"]
        if not var:
            return False
        if name in group.secret_fields():
            return bool(self.environ.get(var))
        return var in self.environ

    def _resolve(
        self, group: type[G], scope: Scope, override: dict | None = None
    ) -> tuple[G, dict[str, Source]]:
        values: dict[str, Any] = {}
        sources: dict[str, Source] = dict.fromkeys(group.model_fields, "default")
        for layer in scope.layers():
            stored = override if override is not None and layer == scope else None
            stored = stored if stored is not None else self.stored(group, layer)[0]
            for name, value in stored.items():
                # a value stored at a level the field no longer allows is ignored (inherited)
                if name in group.model_fields and layer.level in group.meta(name)["scopes"]:
                    values[name] = value
                    sources[name] = layer.level
        for name in group.model_fields:
            if self._env_active(group, name):
                if name not in group.secret_fields():  # a secret's value never enters here
                    values[name] = self.environ[group.meta(name)["env"]]
                sources[name] = "environment variable"
        try:
            return group.model_validate(values), sources
        except ValidationError as e:
            fields = sorted(
                f"{f} (from {group.meta(f)['env']})"
                if sources.get(f) == "environment variable"
                else f
                for f in {str(err["loc"][0]) for err in e.errors() if err["loc"]}
            )
            raise SettingsError(
                f"invalid {group.GROUP} settings at {scope.level}: {fields}"
            ) from None


_MISSING = object()


def _normalize(group: type[SettingsGroup], stored: dict) -> dict:
    """Stored values in their validated JSON form (an imported "8089" is stored as 8089)."""
    full = group.model_validate(stored).model_dump(mode="json")
    return {name: full[name] for name in stored}


def _canonical(body: Any) -> bytes:
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
