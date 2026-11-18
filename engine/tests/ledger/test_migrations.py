"""Migration 005 (rename): the app role and the tas name CHECK, on fresh and on v1 databases."""

from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest

from parsemaxxing.ledger import store as db

OLD, NEW = "parsewright_app", "parsemaxxing_app"
JOB = "legacy01"


def _roles(conn) -> set[str]:
    rows = conn.execute("SELECT rolname FROM pg_roles WHERE rolname IN (%s, %s)", (OLD, NEW))
    return {r["rolname"] if isinstance(r, dict) else r[0] for r in rows}


@pytest.fixture
def fresh_db(pg_dsn):
    """A throwaway database in the test cluster (roles are cluster-wide, databases are not)."""
    admin = urlunsplit(urlsplit(pg_dsn)._replace(path="/postgres"))
    name = "parsemaxxing_mig_test"
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
        conn.execute(f"CREATE DATABASE {name}")
    yield urlunsplit(urlsplit(pg_dsn)._replace(path=f"/{name}"))
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
        if OLD in _roles(conn) and NEW not in _roles(conn):  # a failed test: undo the rename
            conn.execute(f"ALTER ROLE {OLD} RENAME TO {NEW}")


def _apply_v1(conn) -> None:
    """001-004 exactly as a v1 volume applied them, tracked by file name."""
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (name text PRIMARY KEY)")
    for path in sorted(db.MIGRATIONS.glob("00[1-4]_*.sql")):
        with conn.transaction():
            conn.execute(path.read_text(encoding="utf-8"))
            conn.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (path.name,))


def _insert_ta(conn, app: str) -> None:
    conn.execute(
        "INSERT INTO tas (app, sourcetype, vendor, product, owner_job, current_version)"
        " VALUES (%s, 'acme:fw', 'acme', 'fw', %s, '1.0.0')",
        (app, JOB),
    )


def _check_names(conn) -> None:
    conn.execute(
        "INSERT INTO jobs (id, status, source_key, content_sha256, sample_path)"
        " VALUES (%s, 'done', 'k', %s, 'x') ON CONFLICT DO NOTHING",
        (JOB, "a" * 64),
    )
    _insert_ta(conn, "TA-parsemaxxing-acme-fw")
    for bad in ("TA-acme-fw", "TA-evil-acme-fw", "TA-parsemaxxing-acme-fw__test_x", "x"):
        with pytest.raises(psycopg.errors.CheckViolation), conn.transaction():
            _insert_ta(conn, bad)


def _app_role_works(conn) -> None:
    conn.execute(f"SET ROLE {NEW}")
    conn.execute("SELECT count(*) FROM jobs, tas, ta_versions, ta_events, ledger, settings")
    conn.execute("UPDATE tas SET current_version = current_version, updated_at = now()")
    with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
        conn.execute("UPDATE tas SET owner_job = owner_job")
    with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
        conn.execute("TRUNCATE ledger")
    conn.execute("RESET ROLE")


def test_fresh_database_gets_the_new_role_and_names(fresh_db):
    """002 recreates parsewright_app next to the renamed role; 005 leaves only the new one."""
    with db.connect(fresh_db) as conn:
        applied = db.migrate(conn)
        assert applied[-1] == "005_rename_to_parsemaxxing.sql"
        assert _roles(conn) == {NEW}
        _check_names(conn)
        _app_role_works(conn)
        assert db.migrate(conn) == []  # idempotent by file name


def test_v1_volume_is_renamed_in_place_and_keeps_legacy_tas(fresh_db):
    with db.connect(fresh_db) as conn:
        conn.execute(f"ALTER ROLE {NEW} RENAME TO {OLD}")  # the cluster as v1 left it
        _apply_v1(conn)
        conn.execute(
            "INSERT INTO jobs (id, status, source_key, content_sha256, sample_path)"
            " VALUES (%s, 'done', 'k', %s, 'x')",
            (JOB, "a" * 64),
        )
        _insert_ta(conn, "TA-parsewright-x-y")
        with pytest.raises(psycopg.errors.CheckViolation), conn.transaction():
            _insert_ta(conn, "TA-parsemaxxing-acme-fw")  # 003's CHECK, before 005

        assert db.migrate(conn) == ["005_rename_to_parsemaxxing.sql"]
        assert _roles(conn) == {NEW}
        assert conn.execute("SELECT app FROM tas").fetchall() == [{"app": "TA-parsewright-x-y"}]
        _check_names(conn)
        _insert_ta(conn, "TA-parsewright-acme-old")  # legacy prefix still accepted
        _app_role_works(conn)


def test_005_is_safe_to_run_twice(fresh_db):
    """Rerun by hand (e.g. after a restore): no error, nothing changes."""
    sql = (db.MIGRATIONS / "005_rename_to_parsemaxxing.sql").read_text(encoding="utf-8")
    with db.connect(fresh_db) as conn:
        db.migrate(conn)
        conn.execute(sql)
        assert _roles(conn) == {NEW}
        _app_role_works(conn)
