-- Phase 13: local users, MFA, sessions, API tokens, login throttling, the one-time setup token,
-- the append-only and hash-chained auth_events audit table, and jobs.created_by (design 7.3).
--
-- No secret is stored in clear: passwords as Argon2id PHC strings, session ids, API tokens,
-- recovery codes and the setup token as SHA-256 hex, TOTP secrets in the vault (secrets table).

-- =============================================================================================
-- Section 1: accounts and MFA
-- =============================================================================================

CREATE TABLE IF NOT EXISTS users (
    id                   uuid PRIMARY KEY,
    username             text NOT NULL UNIQUE CHECK (username ~ '^[a-z0-9][a-z0-9._-]{0,63}$'),
    display_name         text NOT NULL DEFAULT '' CHECK (length(display_name) <= 128),
    role                 text NOT NULL CHECK (role IN ('viewer', 'admin')),
    source               text NOT NULL DEFAULT 'local' CHECK (source IN ('local')),  -- ldap: 14
    password_hash        text CHECK (password_hash IS NULL OR password_hash LIKE '$argon2id$%'),
    disabled_at          timestamptz,
    password_changed_at  timestamptz,
    last_login_at        timestamptz,
    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now()
);

-- One TOTP enrolment per user; the secret lives in the vault (`secret_id`). confirmed_at NULL:
-- enrolment started, not yet proven. last_step: the newest RFC 6238 time step accepted, so a
-- code is never accepted twice.
CREATE TABLE IF NOT EXISTS user_mfa (
    user_id       uuid PRIMARY KEY REFERENCES users (id),
    secret_id     uuid NOT NULL,
    confirmed_at  timestamptz,
    last_step     bigint NOT NULL DEFAULT 0,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS recovery_codes (
    id          bigserial PRIMARY KEY,
    user_id     uuid NOT NULL REFERENCES users (id),
    code_hash   text NOT NULL UNIQUE CHECK (code_hash ~ '^[0-9a-f]{64}$'),
    used_at     timestamptz,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS recovery_codes_user ON recovery_codes (user_id);

-- =============================================================================================
-- Section 2: sessions and API tokens
-- =============================================================================================

-- `id` is the public handle (lists, revoke); `token_hash` is SHA-256 of the cookie value.
-- stage: 'mfa' (password ok, TOTP pending), 'enrol' (MFA required, not enrolled), 'full'.
-- A stage change is a new row (rotation), so the app role cannot UPDATE stage.
CREATE TABLE IF NOT EXISTS sessions (
    id              uuid PRIMARY KEY,
    token_hash      text NOT NULL UNIQUE CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    user_id         uuid NOT NULL REFERENCES users (id),
    stage           text NOT NULL CHECK (stage IN ('mfa', 'enrol', 'full')),
    created_at      timestamptz NOT NULL DEFAULT now(),
    last_seen_at    timestamptz NOT NULL DEFAULT now(),
    expires_at      timestamptz NOT NULL,
    revoked_at      timestamptz,
    revoked_reason  text,
    ip              text NOT NULL DEFAULT '' CHECK (length(ip) <= 64),
    user_agent      text NOT NULL DEFAULT '' CHECK (length(user_agent) <= 200)
);
CREATE INDEX IF NOT EXISTS sessions_user ON sessions (user_id) WHERE revoked_at IS NULL;

CREATE TABLE IF NOT EXISTS api_tokens (
    id            uuid PRIMARY KEY,
    user_id       uuid NOT NULL REFERENCES users (id),
    name          text NOT NULL CHECK (name ~ '^[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}$'),
    role          text NOT NULL CHECK (role IN ('viewer', 'admin')),
    token_hash    text NOT NULL UNIQUE CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    created_at    timestamptz NOT NULL DEFAULT now(),
    expires_at    timestamptz NOT NULL,
    revoked_at    timestamptz,
    last_used_at  timestamptz,
    CHECK (expires_at > created_at AND expires_at <= created_at + interval '90 days 1 minute')
);
CREATE INDEX IF NOT EXISTS api_tokens_user ON api_tokens (user_id);

-- =============================================================================================
-- Section 3: login throttling and the setup token
-- =============================================================================================

-- Failure counters for lockout with exponential backoff. `key` is SHA-256 of 'user:<name>',
-- 'ip:<address>', 'mfa:<user id>' or 'token-ip:<address>': unknown user names lock exactly like
-- known ones (no enumeration), and a typed name is never stored.
CREATE TABLE IF NOT EXISTS auth_throttle (
    key           text PRIMARY KEY CHECK (key ~ '^[0-9a-f]{64}$'),
    failures      integer NOT NULL CHECK (failures >= 0),
    locked_until  timestamptz,
    updated_at    timestamptz NOT NULL DEFAULT now()
);

-- One row: the current first-run setup token (SHA-256), valid 60 minutes, single use.
CREATE TABLE IF NOT EXISTS setup_token (
    one         boolean PRIMARY KEY DEFAULT true CHECK (one),
    token_hash  text NOT NULL CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    issued_at   timestamptz NOT NULL DEFAULT now(),
    expires_at  timestamptz NOT NULL,
    used_at     timestamptz
);

-- =============================================================================================
-- Section 4: auth_events (append-only, hash-chained like the ledger)
-- =============================================================================================

-- A table of its own rather than ledger rows: ledger rows belong to a job (job_id NOT NULL,
-- served per job to every viewer over the event stream); these are platform-wide and carry
-- client IPs. Same construction as migration 006's ledger chain, its own advisory lock.
CREATE TABLE IF NOT EXISTS auth_events (
    id         bigint PRIMARY KEY,
    at         timestamptz NOT NULL DEFAULT now(),
    actor      text NOT NULL CHECK (length(actor) <= 80),      -- user name, cli:..., anonymous
    user_id    uuid,                                            -- the account concerned
    event      text NOT NULL CHECK (event ~ '^[a-z][a-z_]{1,40}$'),
    outcome    text NOT NULL CHECK (outcome IN ('success', 'failure', 'refused')),
    ip         text NOT NULL DEFAULT '' CHECK (length(ip) <= 64),
    detail     jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(detail) = 'object'),
    prev_hash  text NOT NULL CHECK (prev_hash ~ '^[0-9a-f]{64}$'),
    hash       text NOT NULL CHECK (hash ~ '^[0-9a-f]{64}$')
);
CREATE SEQUENCE IF NOT EXISTS auth_events_id_seq OWNED BY auth_events.id;
CREATE INDEX IF NOT EXISTS auth_events_user ON auth_events (user_id, id);

CREATE OR REPLACE FUNCTION auth_event_row_hash(
    prev text, id bigint, at timestamptz, actor text, user_id uuid, event text, outcome text,
    ip text, detail jsonb
) RETURNS text LANGUAGE sql IMMUTABLE AS $$
    SELECT encode(sha256(convert_to(jsonb_build_array(
        prev, id, to_char(at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US'), actor,
        user_id::text, event, outcome, ip, detail
    )::text, 'UTF8')), 'hex')
$$;

CREATE OR REPLACE FUNCTION auth_events_chain() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    PERFORM pg_advisory_xact_lock(7003);
    NEW.id := nextval('auth_events_id_seq');
    SELECT hash INTO NEW.prev_hash FROM auth_events ORDER BY id DESC LIMIT 1;
    NEW.prev_hash := coalesce(NEW.prev_hash, repeat('0', 64));
    NEW.hash := auth_event_row_hash(NEW.prev_hash, NEW.id, NEW.at, NEW.actor, NEW.user_id,
                                    NEW.event, NEW.outcome, NEW.ip, NEW.detail);
    RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS auth_events_chain ON auth_events;
CREATE TRIGGER auth_events_chain BEFORE INSERT ON auth_events
    FOR EACH ROW EXECUTE FUNCTION auth_events_chain();
DROP TRIGGER IF EXISTS auth_events_no_update ON auth_events;
CREATE TRIGGER auth_events_no_update BEFORE UPDATE OR DELETE ON auth_events
    FOR EACH ROW EXECUTE FUNCTION pmx_append_only();
DROP TRIGGER IF EXISTS auth_events_no_truncate ON auth_events;
CREATE TRIGGER auth_events_no_truncate BEFORE TRUNCATE ON auth_events
    FOR EACH STATEMENT EXECUTE FUNCTION pmx_append_only();

-- =============================================================================================
-- Section 5: who started a job (NULL for v1 rows and `parsemaxxing run`)
-- =============================================================================================

ALTER TABLE jobs ADD COLUMN IF NOT EXISTS created_by text CHECK (length(created_by) <= 64);

-- =============================================================================================
-- Section 6: grants for the engine role. No DELETE except on MFA rows and throttle counters;
-- UPDATE never on ids, user names, hashes of credentials already issued, or stage.
-- =============================================================================================

GRANT SELECT, INSERT ON users TO parsemaxxing_app;
GRANT UPDATE (display_name, role, password_hash, disabled_at, password_changed_at,
              last_login_at, updated_at) ON users TO parsemaxxing_app;
GRANT SELECT, INSERT, DELETE ON user_mfa TO parsemaxxing_app;
GRANT UPDATE (secret_id, confirmed_at, last_step) ON user_mfa TO parsemaxxing_app;
GRANT SELECT, INSERT, DELETE ON recovery_codes TO parsemaxxing_app;
GRANT UPDATE (used_at) ON recovery_codes TO parsemaxxing_app;
GRANT USAGE ON SEQUENCE recovery_codes_id_seq TO parsemaxxing_app;
GRANT SELECT, INSERT ON sessions TO parsemaxxing_app;
GRANT UPDATE (last_seen_at, revoked_at, revoked_reason) ON sessions TO parsemaxxing_app;
GRANT SELECT, INSERT ON api_tokens TO parsemaxxing_app;
GRANT UPDATE (revoked_at, last_used_at) ON api_tokens TO parsemaxxing_app;
GRANT SELECT, INSERT, DELETE ON auth_throttle TO parsemaxxing_app;
GRANT UPDATE (failures, locked_until, updated_at) ON auth_throttle TO parsemaxxing_app;
GRANT SELECT, INSERT ON setup_token TO parsemaxxing_app;
GRANT UPDATE (token_hash, issued_at, expires_at, used_at) ON setup_token TO parsemaxxing_app;
GRANT SELECT, INSERT ON auth_events TO parsemaxxing_app;
GRANT USAGE ON SEQUENCE auth_events_id_seq TO parsemaxxing_app;
