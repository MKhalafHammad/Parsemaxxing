"""Ledger hash chain (migration 006 section 5): every row links to the previous one, the chain
survives concurrent appends, and `ledger verify` finds edited, removed and moved rows, even
when a superuser bypasses the append-only triggers (adversarial)."""

import threading
from contextlib import contextmanager

import psycopg
import pytest
from test_migrations import _apply_v1, fresh_db  # noqa: F401  # fixture

from parsemaxxing.cli import main as cli_main
from parsemaxxing.ledger import store as db


def _job(store, job="chain001"):
    store.enqueue(job, f"chain:{job}", "d" * 64, "/tmp/x", {})  # one "queued" row
    for i in range(4):
        store.event(job, "log", {"line": f"step {i}"})
    return [r["id"] for r in store.conn.execute("SELECT id FROM ledger ORDER BY id")]


@contextmanager
def bypass(conn):
    """What a superuser could do: switch the append-only trigger off around a tampering."""
    conn.execute("ALTER TABLE ledger DISABLE TRIGGER ledger_no_update")
    try:
        yield
    finally:
        conn.execute("ALTER TABLE ledger ENABLE TRIGGER ledger_no_update")


def problems(conn):
    return db.verify_ledger(conn)["problems"]


def test_intact_chain_verifies(pg):
    ids = _job(pg)
    result = db.verify_ledger(pg.conn)
    assert result["problems"] == [] and result["rows"] == len(ids) == 5
    first = pg.conn.execute("SELECT prev_hash FROM ledger ORDER BY id LIMIT 1").fetchone()
    assert first["prev_hash"] == db.GENESIS
    assert result["head"]["id"] == ids[-1]


def test_caller_cannot_choose_id_or_hashes(pg):
    _job(pg)
    pg.conn.execute(
        "INSERT INTO ledger (id, job_id, event, data, prev_hash, hash)"
        " VALUES (1, 'chain001', 'forged', '{}', %s, %s)",
        ("f" * 64, "f" * 64),
    )
    row = pg.conn.execute("SELECT * FROM ledger ORDER BY id DESC LIMIT 1").fetchone()
    assert row["event"] == "forged" and row["id"] != 1 and row["hash"] != "f" * 64
    assert problems(pg.conn) == []


def test_edited_row_is_detected(pg):
    ids = _job(pg)
    with bypass(pg.conn):
        pg.conn.execute("UPDATE ledger SET data = '{\"x\": 1}' WHERE id = %s", (ids[2],))
    assert problems(pg.conn) == [{"id": ids[2], "problem": "content does not match its hash"}]


def test_edited_row_with_recomputed_own_hash_breaks_the_next_link(pg):
    ids = _job(pg)
    with bypass(pg.conn):
        pg.conn.execute(
            "UPDATE ledger SET data = '{}'::jsonb,"
            " hash = ledger_row_hash(prev_hash, id, job_id, at, event, '{}'::jsonb) WHERE id = %s",
            (ids[2],),
        )
    assert [p["id"] for p in problems(pg.conn)] == [ids[3]]


def test_deleted_row_is_detected(pg):
    ids = _job(pg)
    with bypass(pg.conn):
        pg.conn.execute("DELETE FROM ledger WHERE id = %s", (ids[1],))
    assert problems(pg.conn) == [
        {"id": ids[2], "problem": "chain broken before this row (removed or moved)"}
    ]


def test_reordered_rows_are_detected(pg):
    ids = _job(pg)
    a, b = ids[1], ids[3]
    with bypass(pg.conn), pg.conn.transaction():  # swap the two rows' places (their ids)
        pg.conn.execute("UPDATE ledger SET id = -1 WHERE id = %s", (a,))
        pg.conn.execute("UPDATE ledger SET id = %s WHERE id = %s", (a, b))
        pg.conn.execute("UPDATE ledger SET id = %s WHERE id = -1", (b,))
    found = {p["id"] for p in problems(pg.conn)}
    assert {a, b} <= found


def test_superuser_without_triggers_still_cannot_hide_a_swap_of_contents(pg):
    ids = _job(pg)
    with bypass(pg.conn), pg.conn.transaction():
        pg.conn.execute(
            "UPDATE ledger l SET data = o.data FROM ledger o"
            " WHERE (l.id, o.id) IN ((%s, %s), (%s, %s))",
            (ids[1], ids[2], ids[2], ids[1]),
        )
    assert {p["id"] for p in problems(pg.conn)} == {ids[1], ids[2]}


def test_concurrent_appends_keep_one_chain(pg, pg_dsn):
    pg.enqueue("chain002", "chain:2", "c" * 64, "/tmp/x", {})

    def append(n):
        with db.connect(pg_dsn) as conn:
            store = db.Store(conn)
            for i in range(15):
                if i % 5 == 0:  # some appends inside longer transactions
                    with conn.transaction():
                        store.event("chain002", "log", {"w": n, "i": i})
                        store.event("chain002", "log", {"w": n, "i": i, "b": 1})
                else:
                    store.event("chain002", "log", {"w": n, "i": i})

    threads = [threading.Thread(target=append, args=(n,)) for n in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    result = db.verify_ledger(pg.conn, batch=7)  # pages smaller than the ledger
    assert result["problems"] == [] and result["rows"] == 1 + 6 * 18


def test_app_role_appends_but_cannot_rewrite(pg):
    _job(pg)
    pg.conn.execute("SET ROLE parsemaxxing_app")
    try:
        pg.event("chain001", "log", {"as": "app"})
        with pytest.raises(psycopg.errors.InsufficientPrivilege), pg.conn.transaction():
            pg.conn.execute("ALTER TABLE ledger DISABLE TRIGGER ledger_no_update")
        assert problems(pg.conn) == []
    finally:
        pg.conn.execute("RESET ROLE")


def test_cli_verify_exit_codes(pg, pg_dsn, monkeypatch, tmp_path, capsys):
    ids = _job(pg)
    monkeypatch.setenv("DATABASE_URL", pg_dsn)
    argv = ["--env-file", str(tmp_path / "none.env"), "ledger", "verify"]
    assert cli_main(argv) == 0 and "ledger verify: ok" in capsys.readouterr().out
    with bypass(pg.conn):
        pg.conn.execute("DELETE FROM ledger WHERE id = %s", (ids[2],))
    assert cli_main(argv) == 5
    assert f"row {ids[3]}: chain broken" in capsys.readouterr().out


def test_cli_head_and_expect_head(pg, pg_dsn, monkeypatch, tmp_path, capsys):
    """Adversarial: a removed tail, or a chain recomputed by a superuser, passes a plain verify
    but fails against a head recorded earlier."""
    monkeypatch.setenv("DATABASE_URL", pg_dsn)
    base = ["--env-file", str(tmp_path / "none.env"), "ledger"]
    assert cli_main([*base, "head"]) == 0
    assert capsys.readouterr().out.strip() == f"-1:{db.GENESIS}"  # empty ledger
    ids = _job(pg)
    assert cli_main([*base, "head"]) == 0
    head = capsys.readouterr().out.strip()
    assert head == f"{ids[-1]}:{db.verify_ledger(pg.conn)['head']['hash']}"
    assert cli_main([*base, "verify", "--expect-head", head]) == 0
    assert cli_main([*base, "verify", f"--expect-head=-1:{db.GENESIS}"]) == 0
    capsys.readouterr()
    for bad in ("7", f"x:{'a' * 64}", f"{ids[-1]}:{'A' * 64}", f"1:{'a' * 64}\nrow 1: ok"):
        assert cli_main([*base, "verify", "--expect-head", bad]) == 4
    assert "--expect-head is" in capsys.readouterr().err
    # A newer row: the old anchor still holds.
    pg.event("chain001", "log", {"line": "later"})
    assert cli_main([*base, "verify", "--expect-head", head]) == 0
    # Remove the tail back to before the anchor: the chain alone is intact, the anchor is not.
    with bypass(pg.conn):
        pg.conn.execute("DELETE FROM ledger WHERE id >= %s", (ids[-1],))
    assert db.verify_ledger(pg.conn)["problems"] == []
    capsys.readouterr()
    assert cli_main([*base, "verify", "--expect-head", head]) == 5
    out = capsys.readouterr()
    assert f"row {ids[-1]}: the expected head row is gone" in out.out and "FAILED" in out.err


def test_expect_head_detects_a_recomputed_chain(pg):
    ids = _job(pg)
    head = db.ledger_head(pg.conn)
    with bypass(pg.conn):  # a superuser edits a row and recomputes every hash from it on
        pg.conn.execute('UPDATE ledger SET data = \'{"line": "forged"}\' WHERE id = %s', (ids[1],))
        for i in ids[1:]:
            pg.conn.execute(
                "UPDATE ledger l SET prev_hash = p.hash FROM ledger p"
                " WHERE l.id = %s AND p.id = (SELECT max(id) FROM ledger WHERE id < %s)",
                (i, i),
            )
            pg.conn.execute(
                "UPDATE ledger SET hash = ledger_row_hash(prev_hash, id, job_id, at, event, data)"
                " WHERE id = %s",
                (i,),
            )
    assert problems(pg.conn) == []
    assert db.verify_ledger(pg.conn, expect_head=head)["problems"] == [
        {"id": ids[-1], "problem": "the expected head row changed"}
    ]
    with pytest.raises(ValueError):
        db.verify_ledger(pg.conn, expect_head="1:short")


def test_migration_backfills_existing_rows_in_order(fresh_db):  # noqa: F811
    with db.connect(fresh_db) as conn:
        _apply_v1(conn)  # 001-004: a v1 ledger without hashes
        conn.execute(
            "INSERT INTO jobs (id, status, source_key, content_sha256, sample_path)"
            " VALUES ('old00001', 'done', 'k', %s, 'x')",
            ("a" * 64,),
        )
        for i in range(5):
            conn.execute(
                "INSERT INTO ledger (job_id, event, data) VALUES ('old00001', 'log', %s)",
                (psycopg.types.json.Jsonb({"i": i}),),
            )
        db.migrate(conn)
        db.Store(conn).event("old00001", "log", {"after": "migration"})
        result = db.verify_ledger(conn)
        assert result["problems"] == [] and result["rows"] == 6
