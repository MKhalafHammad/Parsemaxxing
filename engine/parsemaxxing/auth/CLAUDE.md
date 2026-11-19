# auth/ (accounts, sessions, MFA, API tokens, route policy)

Root rules in [../../../CLAUDE.md](../../../CLAUDE.md) and [../../CLAUDE.md](../../CLAUDE.md) apply.
Design: [7.3, 7.4](../../../docs/design.md), D6. Threats T11.1-T11.12, T12.1-T12.8. Baseline
A01-1..5, A07-1..5, LDAP-1..6.

## What it does
- `policy.py`: `require(Role.X)` dependencies, `PUBLIC` (the only anonymous routes),
  `check_routes(app)` (run by `create_app`: the engine does not start with a route lacking a
  policy), client IP (X-Forwarded-For only from `PARSEMAXXING_TRUSTED_PROXIES`), the cookie.
- `service.py`: login (password, then MFA), lockout, sessions, tokens, users, TOTP, recovery
  codes, setup token, break-glass `admin_reset`, directory users (provisioning, role from
  groups). `routes.py`: the HTTP API. `events.py`: audit.
- `ldap.py`: the directory client (`Directory`: authenticate, lookup, test_connection), the CA
  bundle check and the TLS context.
- Tables: migrations `007_auth.sql`, `008_ldap_users.sql`. Settings: `AuthSettings`,
  `LdapSettings` (`settings/groups.py`).

## Invariants (do not weaken)
- Deny by default: a new route depends on `Viewer`, `Admin`, `SignedIn`, `AdminSession`,
  `Account`, `Pending` or `AnySession`, or is added to `PUBLIC` (no path parameters there).
  The middleware also answers 401 before the body is read when a non-public request has no
  cookie and no `Authorization` header.
- Authorization only in the engine; the UI is never the control.
- Store only hashes: Argon2id (RFC 9106 low-memory, above OWASP) for passwords; SHA-256 for
  session ids, `pmxt_` tokens, recovery codes, the setup token. TOTP secrets only in the vault.
- One login failure message and the same Argon2 work for unknown, disabled and wrong password;
  unknown user names lock exactly like known ones; throttle keys are hashed (a typed name is
  never stored). Audit rows never hold a password, token, session id, code or unknown name.
- New session id at every login, MFA completion, password or MFA change; all of a user's
  sessions revoked on password, MFA, role change, disable and admin reset; all of their API
  tokens on password, role change, disable and admin reset. MFA enrolment on a full session
  re-enters the password. An open event stream re-checks its credential every `RECHECK_S`.
- Tokens: role at most the creator's, effective role at most the owner's current role, expiry
  1-90 days, session-only creation (a token cannot mint tokens or change the account).
- TOTP: ±1 step, a step at or before `last_step` is refused (replay).
- Never leave zero active admins (advisory lock `ADMIN_LOCK`).
- A cookie-bearing state change needs an allowed `Origin` and `X-Parsemaxxing: 1` (api/app.py).
- `auth_events` is append-only and hash-chained (`ledger verify` checks it); its own table
  because ledger rows belong to a job and are streamed to viewers.

## LDAP invariants (do not weaken)
- LDAPS or StartTLS only: `LdapServer` refuses plain `ldap://`, and `Directory._open` refuses
  again and checks the socket is TLS before any bind. Trust only the uploaded CA bundle
  (`tls_context`: never the system store); host name always checked by the standard library
  (`_VerifiedTls`; ldap3's own check is not used).
- An empty password is refused before any connection (`authenticate`) and again in `_bound`.
- The user name goes into the filter only through `escape_filter_chars`; DNs in group filters
  too. Exactly one entry or fail; never pick one of several.
- No mapped group means no access; the highest mapped role wins; groups are re-read at every
  sign-in and a changed role revokes the user's sessions and tokens.
- A name that is a local account never goes to the directory (break-glass works when it is
  down); a directory name that equals a local account is refused, never merged. Directory
  rows have no password hash (CHECK in 008), no API tokens, no manual role, no local password
  change, and are not counted as break-glass admins (`_keeps_an_admin` counts local ones).
- Every directory failure is the one `LOGIN_FAILED` with Argon2 work, padded to
  `failure_min_seconds` like a local failure; the reason code goes only to `auth_events`.
  Failures count per typed name, IP and directory identity. An outage is audited but not
  counted towards lockout.
- Fail over only on transport errors; any bind result is an answer.
- A directory row is bound to its entry's identity (`directory_id`); a different identity is
  refused, never re-bound.
- The stored bind password never reaches a new endpoint: changing servers or the CA bundle
  needs `bind_password` again and the admin's `current_password`; it also revokes every
  directory session, as does turning LDAP off.
- The bind password is decrypted only inside `Auth.directory()`; `Directory`'s repr is
  redacted; never log, raise or return an ldap3 `Connection` (its repr shows the password).
  Connection tests return step results, never server text or a password.

## Changes that need an adversarial test (engine/tests/auth/test_auth.py)
- Any new route: the role matrix test covers it automatically; add object checks for its ids.
- Login, MFA, throttle: enumeration (message and timing), lockout, replay, recovery reuse.
- Sessions and cookie: fixation, idle and absolute timeouts, revocation, cookie flags.
- Tokens: escalation through creation, expiry, revocation, owner demotion.
- Setup token: reuse, expiry, race. Anything touching a credential: the leak scan.
- LDAP (engine/tests/auth/test_ldap.py, MOCK_SYNC; test_ldap_integration.py, real OpenLDAP):
  escaping and injection, exactly one entry, empty password, TLS (plain, wrong CA, host
  name), failover, group modes, no-group denial, group change at next sign-in, local name
  conflict, break-glass while the directory is down, the bind-password leak scan.
