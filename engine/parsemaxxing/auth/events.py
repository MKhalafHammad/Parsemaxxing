"""auth_events: the append-only, hash-chained audit table (migration 007, section 4).

Rows hold who, what, outcome, client IP and a small detail object. Never a password, token,
session id, TOTP or recovery code, or a user name typed for an unknown account.
"""

from typing import Any

import psycopg
from psycopg.types.json import Jsonb

GENESIS = "0" * 64


def record(
    conn: psycopg.Connection,
    event: str,
    outcome: str,
    actor: str,
    user_id: str | None = None,
    ip: str = "",
    **detail: Any,
) -> None:
    conn.execute(
        "INSERT INTO auth_events (actor, user_id, event, outcome, ip, detail, prev_hash, hash)"
        " VALUES (%s, %s, %s, %s, %s, %s, '', '')",  # the trigger sets id and both hashes
        (actor[:80], user_id, event, outcome, ip[:64], Jsonb(detail)),
    )


def recent(
    conn: psycopg.Connection, limit: int = 100, before: int | None = None, event: str | None = None
) -> list[dict]:
    return conn.execute(
        "SELECT id, at, actor, user_id, event, outcome, ip, detail FROM auth_events"
        " WHERE (%(before)s::bigint IS NULL OR id < %(before)s)"
        " AND (%(event)s::text IS NULL OR event = %(event)s) ORDER BY id DESC LIMIT %(limit)s",
        {"before": before, "event": event, "limit": min(max(limit, 1), 500)},
    ).fetchall()


def verify(conn: psycopg.Connection, batch: int = 5000, cap: int = 100) -> dict:
    """Walk the chain in id order, as `ledger.store.verify_ledger` does for the ledger."""
    rows, last, after, problems = 0, GENESIS, -1, []
    while True:
        page = conn.execute(
            "SELECT id, prev_hash, hash, auth_event_row_hash(prev_hash, id, at, actor, user_id,"
            " event, outcome, ip, detail) AS expected FROM auth_events WHERE id > %s"
            " ORDER BY id LIMIT %s",
            (after, batch),
        ).fetchall()
        if not page:
            return {"rows": rows, "head": {"id": after, "hash": last}, "problems": problems[:cap]}
        for r in page:
            if r["hash"] != r["expected"]:
                problems.append({"id": r["id"], "problem": "content does not match its hash"})
            if r["prev_hash"] != last:
                problems.append({"id": r["id"], "problem": "chain broken before this row"})
            rows, last, after = rows + 1, r["hash"], r["id"]
