# ledger

PostgreSQL models for the job queue and the append-only run ledger, written on every state transition.

Status: built: `migrations/` (001 jobs and ledger, 002 final states and the limited app role, 003–004 the TA registry, 005 rename, 006 settings, vault and the ledger hash chain), `store.py` (queue, leases, guarded transitions, append-only ledger with NOTIFY, usage, kill switch, advisory locks, `verify_ledger`), `backup.py` (encrypted backups). See [docs/design.md](../../../docs/design.md), section "Concurrency and continuous operation".

## Hash chain (migration 006, section 5)

- Every ledger row has `prev_hash` (the previous row's `hash`, 64 zeros for the first) and `hash` = SHA-256 of the JSON array `[prev_hash, id, job_id, at (UTC, microseconds), event, data]` (SQL function `ledger_row_hash`).
- A `BEFORE INSERT` trigger computes both and assigns the id after a transaction-level advisory lock (7002), so appends are serialised and id order is commit order. Values a caller sends for `id`, `prev_hash` or `hash` are replaced. Existing rows were backfilled in id order.
- Rows are written only through `Store.event` (a test greps for any other `INSERT INTO ledger`).
- `parsemaxxing ledger verify` (exit 5 on a problem) reports rows whose content no longer matches their hash (edited, or moved to another id) and rows whose `prev_hash` does not match the row before (a row removed or moved), even when a superuser bypassed the append-only triggers. It prints the head (id, hash): a removed *tail* is detectable only against a head recorded earlier, and a superuser who recomputes the whole chain is not detected (no external anchor yet).

## Backups (`backup.py`)

- `parsemaxxing backup [--out-dir backups]`: `pg_dump --format=custom` (owner account) piped to `age --encrypt --recipient <backup.age_recipient>`; folder 0700, file `pmx-<UTC>.dump.age` 0600; this tool's backups older than 30 days are pruned at each run (design 7.19). The recipient is the settings field `backup.age_recipient` (platform), overridable by `PARSEMAXXING_BACKUP_RECIPIENT`.
- `parsemaxxing restore <file> --identity <age key file> --target-dsn <dsn> --yes`: `age --decrypt` piped to `pg_restore --clean --if-exists --no-owner --single-transaction --exit-on-error`. Roles are cluster-wide and not in the dump: `parsemaxxing_app` must exist on the target cluster (restore on the same cluster, or run `parsemaxxing migrate` on an empty database there first).
- The database password reaches `pg_dump`/`pg_restore` only as `PGPASSWORD`, never on a command line; nothing logs it or the identity. The add-on package store (design 7.15) is not in the backup yet (planned).
