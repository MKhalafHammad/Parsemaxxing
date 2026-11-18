-- Phase 12: settings store, settings history, job settings snapshots and the secrets vault
-- (design 7.5). Later Phase 12 sections (ledger hash chain) are appended below their own header.
--
-- Scope columns everywhere: environment = '' and client = '' is the platform; a client always
-- belongs to an environment. 001's `settings` table (the kill switch) is unrelated and stays.

-- =============================================================================================
-- Section 1: shared append-only trigger function
-- =============================================================================================

CREATE OR REPLACE FUNCTION pmx_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% is append-only (% refused)', TG_TABLE_NAME, TG_OP;
END $$;

-- =============================================================================================
-- Section 2: settings (settings/service.py)
-- =============================================================================================

-- One row per group and scope; `value` holds only the fields explicitly set at that scope
-- (inherited and default values are resolved in code). Secret fields hold vault ids only.
CREATE TABLE IF NOT EXISTS settings_groups (
    environment     text NOT NULL DEFAULT '' CHECK (environment ~ '^([a-z0-9][a-z0-9_-]{0,62})?$'),
    client          text NOT NULL DEFAULT '' CHECK (client ~ '^([a-z0-9][a-z0-9_-]{0,62})?$'),
    grp             text NOT NULL CHECK (grp ~ '^[a-z][a-z0-9_]{0,62}$' AND grp <> 'vault'),
    version         integer NOT NULL CHECK (version >= 1),   -- change counter, optimistic lock
    schema_version  integer NOT NULL CHECK (schema_version >= 1),
    value           jsonb NOT NULL CHECK (jsonb_typeof(value) = 'object'),
    updated_by      text NOT NULL,
    updated_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (environment, client, grp),
    CHECK (client = '' OR environment <> '')
);

-- Every change to a setting or a secret. Secret changes carry no value at all (CHECK).
CREATE TABLE IF NOT EXISTS settings_history (
    id           bigserial PRIMARY KEY,
    at           timestamptz NOT NULL DEFAULT now(),
    actor        text NOT NULL,
    environment  text NOT NULL DEFAULT '',
    client       text NOT NULL DEFAULT '',
    grp          text NOT NULL,     -- a settings group, or 'vault' for secrets
    field        text NOT NULL,     -- a field name, or the secret name
    action       text NOT NULL CHECK (action IN ('set', 'reset', 'secret_changed',
                                                 'kek_rotated')),
    old_value    jsonb,             -- SQL NULL: not set at this scope (inherited)
    new_value    jsonb,
    redacted     boolean NOT NULL DEFAULT false,
    CHECK (NOT redacted OR (old_value IS NULL AND new_value IS NULL)),
    CHECK (redacted OR action NOT IN ('secret_changed', 'kek_rotated'))
);
CREATE INDEX IF NOT EXISTS settings_history_scope ON settings_history (environment, client, id);

-- The effective settings a job ran with, addressed by the SHA-256 of their canonical JSON.
CREATE TABLE IF NOT EXISTS settings_snapshots (
    hash        text PRIMARY KEY CHECK (hash ~ '^[0-9a-f]{64}$'),
    body        jsonb NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);

DROP TRIGGER IF EXISTS settings_history_no_update ON settings_history;
CREATE TRIGGER settings_history_no_update BEFORE UPDATE OR DELETE ON settings_history
    FOR EACH ROW EXECUTE FUNCTION pmx_append_only();
DROP TRIGGER IF EXISTS settings_history_no_truncate ON settings_history;
CREATE TRIGGER settings_history_no_truncate BEFORE TRUNCATE ON settings_history
    FOR EACH STATEMENT EXECUTE FUNCTION pmx_append_only();
DROP TRIGGER IF EXISTS settings_snapshots_no_update ON settings_snapshots;
CREATE TRIGGER settings_snapshots_no_update BEFORE UPDATE OR DELETE ON settings_snapshots
    FOR EACH ROW EXECUTE FUNCTION pmx_append_only();
DROP TRIGGER IF EXISTS settings_snapshots_no_truncate ON settings_snapshots;
CREATE TRIGGER settings_snapshots_no_truncate BEFORE TRUNCATE ON settings_snapshots
    FOR EACH STATEMENT EXECUTE FUNCTION pmx_append_only();

-- =============================================================================================
-- Section 3: secrets vault (secrets/vault.py)
-- =============================================================================================

-- AES-256-GCM envelope: `ciphertext` under a per-secret data key (DEK) with `nonce`; the DEK
-- wrapped by the KEK with `dek_nonce`. Both AADs bind id, scope, name and version.
CREATE TABLE IF NOT EXISTS secrets (
    id           uuid PRIMARY KEY,
    environment  text NOT NULL DEFAULT '' CHECK (environment ~ '^([a-z0-9][a-z0-9_-]{0,62})?$'),
    client       text NOT NULL DEFAULT '' CHECK (client ~ '^([a-z0-9][a-z0-9_-]{0,62})?$'),
    name         text NOT NULL CHECK (name ~ '^[a-z][a-z0-9_.:-]{0,127}$'),
    version      integer NOT NULL CHECK (version >= 1),
    dek_nonce    bytea NOT NULL CHECK (length(dek_nonce) = 12),
    wrapped_dek  bytea NOT NULL CHECK (length(wrapped_dek) = 48),
    nonce        bytea NOT NULL CHECK (length(nonce) = 12),
    ciphertext   bytea NOT NULL,
    updated_by   text NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (environment, client, name),
    CHECK (client = '' OR environment <> '')
);

-- The id (an HMAC fingerprint) of the KEK every DEK is wrapped with: an engine holding a stale
-- or wrong KEK is refused before it decrypts or writes anything. One row.
CREATE TABLE IF NOT EXISTS vault_kek (
    one         boolean PRIMARY KEY DEFAULT true CHECK (one),
    kek_id      text NOT NULL CHECK (kek_id ~ '^[0-9a-f]{32}$'),
    rotated_at  timestamptz NOT NULL DEFAULT now()
);

-- =============================================================================================
-- Section 4: grants for the engine role (style of 002-005)
-- =============================================================================================

-- History and snapshots: SELECT and INSERT only (append-only even against the engine).
-- Settings and secrets: no DELETE, and UPDATE never on the scope or name columns.
GRANT SELECT, INSERT ON settings_history, settings_snapshots TO parsemaxxing_app;
GRANT USAGE ON SEQUENCE settings_history_id_seq TO parsemaxxing_app;
GRANT SELECT, INSERT ON settings_groups TO parsemaxxing_app;
GRANT UPDATE (version, schema_version, value, updated_by, updated_at)
    ON settings_groups TO parsemaxxing_app;
GRANT SELECT, INSERT ON secrets TO parsemaxxing_app;
GRANT UPDATE (version, dek_nonce, wrapped_dek, nonce, ciphertext, updated_by, updated_at)
    ON secrets TO parsemaxxing_app;
GRANT SELECT, INSERT ON vault_kek TO parsemaxxing_app;
GRANT UPDATE (kek_id, rotated_at) ON vault_kek TO parsemaxxing_app;

-- =============================================================================================
-- Section 5: ledger hash chain (design 7.7 A08; `parsemaxxing ledger verify`)
-- =============================================================================================

-- Each row: hash = SHA-256 over its prev_hash and content; prev_hash = the previous row's hash
-- (64 zeros for the first). The content is a JSON array, so no field can bleed into another,
-- and the time is written in UTC, so the session's TimeZone cannot change a hash.
CREATE OR REPLACE FUNCTION ledger_row_hash(
    prev text, id bigint, job_id text, at timestamptz, event text, data jsonb
) RETURNS text LANGUAGE sql IMMUTABLE AS $$
    SELECT encode(sha256(convert_to(jsonb_build_array(
        prev, id, job_id, to_char(at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US'), event, data
    )::text, 'UTF8')), 'hex')
$$;

ALTER TABLE ledger ADD COLUMN IF NOT EXISTS prev_hash text;
ALTER TABLE ledger ADD COLUMN IF NOT EXISTS hash text;

-- Backfill in id order (the owner runs migrations; the append-only trigger is paused only here).
ALTER TABLE ledger DISABLE TRIGGER ledger_no_update;
DO $$
DECLARE
    r record;
    prev text := repeat('0', 64);
BEGIN
    FOR r IN SELECT * FROM ledger ORDER BY id LOOP
        UPDATE ledger SET prev_hash = prev,
                          hash = ledger_row_hash(prev, r.id, r.job_id, r.at, r.event, r.data)
         WHERE id = r.id RETURNING hash INTO prev;
    END LOOP;
END $$;
ALTER TABLE ledger ENABLE TRIGGER ledger_no_update;
ALTER TABLE ledger ALTER COLUMN prev_hash SET NOT NULL;
ALTER TABLE ledger ALTER COLUMN hash SET NOT NULL;
ALTER TABLE ledger ADD CONSTRAINT ledger_hash_format
    CHECK (prev_hash ~ '^[0-9a-f]{64}$' AND hash ~ '^[0-9a-f]{64}$');

-- Appends are serialised: the transaction-level lock is held until commit, and the id is taken
-- only after it, so id order is commit order and each row links to the last committed one.
-- Whatever id, prev_hash or hash a caller sends is replaced.
CREATE OR REPLACE FUNCTION ledger_chain() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    PERFORM pg_advisory_xact_lock(7002);
    NEW.id := nextval('ledger_id_seq');
    SELECT hash INTO NEW.prev_hash FROM ledger ORDER BY id DESC LIMIT 1;
    NEW.prev_hash := coalesce(NEW.prev_hash, repeat('0', 64));
    NEW.hash := ledger_row_hash(NEW.prev_hash, NEW.id, NEW.job_id, NEW.at, NEW.event, NEW.data);
    RETURN NEW;
END $$;
ALTER TABLE ledger ALTER COLUMN id DROP DEFAULT;  -- the trigger assigns it, after the lock
DROP TRIGGER IF EXISTS ledger_chain ON ledger;
CREATE TRIGGER ledger_chain BEFORE INSERT ON ledger FOR EACH ROW EXECUTE FUNCTION ledger_chain();
