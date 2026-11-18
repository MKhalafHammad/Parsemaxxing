-- Rename (Parsewright -> Parsemaxxing). 001-004 are applied by file name and stay unedited.

-- The engine role: renamed in place, so every grant follows it (RENAME keeps privileges and a
-- SCRAM password; `parsemaxxing migrate` sets the password again anyway).
-- Roles are cluster-wide: a database created after another one ran this has a parsewright_app
-- recreated by 002 next to the renamed role. Its grants here are revoked and the role dropped
-- if nothing else uses it; parsemaxxing_app gets the same grants below.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'parsewright_app') THEN
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'parsemaxxing_app') THEN
            ALTER ROLE parsewright_app RENAME TO parsemaxxing_app;
        ELSE
            REVOKE ALL ON ALL TABLES IN SCHEMA public FROM parsewright_app;
            REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM parsewright_app;
            REVOKE ALL ON SCHEMA public FROM parsewright_app;
            BEGIN
                DROP ROLE parsewright_app;
            EXCEPTION WHEN dependent_objects_still_exist THEN
                NULL;  -- still granted in another database: that database's 005 drops it
            END;
        END IF;
    ELSIF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'parsemaxxing_app') THEN
        CREATE ROLE parsemaxxing_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
END $$;

-- The grants of 002-004, idempotent: a no-op after the rename, the full set otherwise.
GRANT USAGE ON SCHEMA public TO parsemaxxing_app;
GRANT SELECT, INSERT ON ledger TO parsemaxxing_app;
GRANT USAGE ON SEQUENCE ledger_id_seq TO parsemaxxing_app;
GRANT SELECT, INSERT, UPDATE ON jobs, usage, settings TO parsemaxxing_app;
GRANT SELECT, INSERT ON tas TO parsemaxxing_app;
GRANT UPDATE (current_version, updated_at) ON tas TO parsemaxxing_app;
GRANT SELECT, INSERT ON ta_versions, ta_events TO parsemaxxing_app;
GRANT USAGE ON SEQUENCE ta_events_id_seq TO parsemaxxing_app;

-- New add-ons are TA-parsemaxxing-*; TA-parsewright-* add-ons already built stay valid (legacy).
-- The rest of the pattern is exactly 003's.
ALTER TABLE tas DROP CONSTRAINT IF EXISTS tas_app_check;
ALTER TABLE tas ADD CONSTRAINT tas_app_check
    CHECK (app ~ '^TA-(parsemaxxing|parsewright)-[a-z0-9_:-]+-[a-z0-9_:-]+$'
           AND app !~ '__test_');
