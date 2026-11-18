# auth/ (accounts, sessions, MFA, API tokens, route policy)

Root rules in [../../../CLAUDE.md](../../../CLAUDE.md) and [../../CLAUDE.md](../../CLAUDE.md) apply.
Design: [7.3](../../../docs/design.md), D6. Threats T11.1-T11.12. Baseline A01-1..5, A07-1..5.

## What it does
- `policy.py`: `require(Role.X)` dependencies, `PUBLIC` (the only anonymous routes),
  `check_routes(app)` (run by `create_app`: the engine does not start with a route lacking a
  policy), client IP (X-Forwarded-For only from `PARSEMAXXING_TRUSTED_PROXIES`), the cookie.
- `service.py`: login (password, then MFA), lockout, sessions, tokens, users, TOTP, recovery
  codes, setup token, break-glass `admin_reset`. `routes.py`: the HTTP API. `events.py`: audit.
- Tables: migration `007_auth.sql`. Settings: `AuthSettings` (`settings/groups.py`).

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

## Changes that need an adversarial test (engine/tests/auth/test_auth.py)
- Any new route: the role matrix test covers it automatically; add object checks for its ids.
- Login, MFA, throttle: enumeration (message and timing), lockout, replay, recovery reuse.
- Sessions and cookie: fixation, idle and absolute timeouts, revocation, cookie flags.
- Tokens: escalation through creation, expiry, revocation, owner demotion.
- Setup token: reuse, expiry, race. Anything touching a credential: the leak scan.
