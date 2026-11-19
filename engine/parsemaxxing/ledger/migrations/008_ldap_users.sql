-- Phase 14: directory (LDAP) users get a local row so sessions, tokens, audit and created_by
-- work for them (design 7.4). The row never holds a password: the directory checks it at every
-- sign-in, and the role is re-read from the directory groups then.

ALTER TABLE users DROP CONSTRAINT IF EXISTS users_source_check;
ALTER TABLE users ADD CONSTRAINT users_source_check CHECK (source IN ('local', 'ldap'));

ALTER TABLE users DROP CONSTRAINT IF EXISTS users_ldap_no_password;
ALTER TABLE users ADD CONSTRAINT users_ldap_no_password
    CHECK (source <> 'ldap' OR password_hash IS NULL);

-- Directory names may be a userPrincipalName (`avery@acme.example`); local names keep the
-- Phase 13 pattern.
ALTER TABLE users DROP CONSTRAINT IF EXISTS users_username_check;
ALTER TABLE users ADD CONSTRAINT users_username_check CHECK (
    username ~ '^[a-z0-9][a-z0-9._-]{0,63}$'
    OR (source = 'ldap' AND username ~ '^[a-z0-9][a-z0-9._@-]{0,127}$')
);

-- The directory entry's stable identity (entryUUID, objectGUID, else the DN), set at first
-- sign-in. A later sign-in whose entry has another identity is refused: a re-created or renamed
-- entry that reuses a user name never inherits that user's row (sessions, MFA, audit).
ALTER TABLE users ADD COLUMN IF NOT EXISTS directory_id text
    CHECK (directory_id IS NULL OR (source = 'ldap' AND length(directory_id) <= 1100));
CREATE UNIQUE INDEX IF NOT EXISTS users_directory_id ON users (directory_id)
    WHERE directory_id IS NOT NULL;
GRANT UPDATE (directory_id) ON users TO parsemaxxing_app;
