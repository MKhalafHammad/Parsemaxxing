# auth

Local accounts, directory (LDAP) sign-in, sessions, TOTP MFA, API tokens, the route policy
registry and the audit table (design 7.3, 7.4).

## Roles
`viewer` sees everything except secret values and changes nothing (own account, own viewer
tokens excepted); `admin` operates the platform. Any admin can approve (D6).

## Using it in a route
```python
from parsemaxxing.auth.policy import Admin, StoreDep, Viewer


@app.get("/things")
def things(_: Viewer, store: StoreDep) -> list[dict]: ...


@app.post("/things")
def make(who: Admin, store: StoreDep) -> dict: ...  # who.username, who.user_id
```
A route with no policy and not in `policy.PUBLIC` makes `create_app` raise.

## First run and break-glass
- With no admin, the engine writes a one-time setup token (60 minutes, single use) to
  `<runs dir>/setup-token` (`/app/.runs/setup-token` in the container, mode 0600) and logs only
  the path. Every engine worker keeps the token already there while it is unexpired, unused and
  its file is present (under the `ADMIN_LOCK` advisory lock); `parsemaxxing setup-token` always
  writes and prints a new one. `POST /setup` creates the first admin, who then enrols MFA.
- `parsemaxxing admin reset <user>` (database owner credentials, on the host): new password
  read without echo, MFA cleared, account enabled and unlocked (login and MFA throttles), every
  session and API token revoked, audited.
- API tokens are also revoked on a password change, a role change and disable.
- `POST /auth/mfa/enrol` takes `{"password": "..."}` (required on a "full" session; a session in
  stage "enrol" may send no body). `GET /auth/me` returns `mfa_required` (admin and
  `require_mfa_admins` on).
- An open `/runs/{job}/stream` re-checks its session or token every 15 s (not counted as
  activity) and closes once it is revoked, expired or no longer passes the route's role.

## The CLI goes through the API
`run`, `update`, `approve`, `reject`, `promote`, `rollback` and `kill` call the engine API, so
they pass the same role checks and leave the same audit rows as the UI. The token (`pmxt_`,
admin for these commands) comes from `PARSEMAXXING_API_TOKEN` or `--token-file <path>` (a
regular file, mode 0600 or 0400, not a link); it is never a command-line value (no `--token`,
abbreviations off) and never printed. `PARSEMAXXING_API_URL` (default `http://127.0.0.1:8080`)
takes plain http only for `localhost`, `127.0.0.1`, `::1` or `engine`; anything else needs
https. Requests carry `Authorization: Bearer` (dropped on a redirect, which is refused anyway;
environment proxies are ignored) and `X-Parsemaxxing: 1`. A refusal prints the envelope's
message and request id and exits 4. `run`, `update` and `promote` wait for the engine's worker
pool (Ctrl-C stops waiting, not the run); `run --max-attempts` needs `--local`.

Straight to the database: the read-only `status` and `tas`; the engine processes `serve` and
`worker`; and the host-only break-glass commands `migrate`, `admin reset`, `setup-token`,
`secrets rotate-kek`, `settings import-env`, `ledger verify|head`, `backup` and `restore`. They
must work while the API is down or before the first admin exists, or need the database owner
or the KEK, which the API never holds. `run --local` uses neither the API nor PostgreSQL.
`docker compose exec engine parsemaxxing setup-token` works with the engine container's own
app-role credentials (no owner credentials needed).

## Cookie and CSRF
`__Host-pmx_session`: `Secure`, `HttpOnly`, `SameSite=Strict`, `Path=/`, no `Domain`. Chromium
and Firefox treat `http://localhost` as a secure context and keep `Secure` / `__Host-` cookies
there, so the local stack works over plain http on localhost (Playwright Chromium included);
Safari does not, and any other host name needs the `https` profile. Every state-changing request
needs `X-Parsemaxxing: 1`; one that carries the cookie also needs an `Origin` listed in
`WEB_ORIGINS` (a comma list; `WEB_ORIGIN` as a single-value fallback), which also sets CORS.
API tokens go in `Authorization: Bearer pmxt_...` (no Origin needed, no cookie).

## Settings (`auth` group, platform)
`require_mfa_admins` (on), `idle_timeout_minutes` (30), `absolute_timeout_hours` (12),
`lockout_threshold` (5 per user name), `ip_lockout_threshold` (20 per IP),
`lockout_base_seconds` (60, doubling), `lockout_max_seconds` (900). Bootstrap:
`PARSEMAXXING_TRUSTED_PROXIES` (IPs or CIDRs whose `X-Forwarded-For` gives the client IP).

## Directory sign-in (LDAP, Phase 14)
One form for everyone. A name that is a local account is checked locally and never touches the
directory, so local accounts (the break-glass admins) work while it is down. Any other name goes
to the directory when `ldap.enabled` is on: an empty password is refused before any connection;
service bind; search under `user_search_base` with `user_filter`, each `{username}` replaced by
the RFC 4515-escaped name; exactly one entry or fail; bind as that entry's DN; read groups; the
highest role in `group_roles`; no mapped group, no access. Every failure is the same "Sign-in
failed" with the same Argon2 work as a local one, is held until `auth.failure_min_seconds`
(1 s) after it started (local and directory names, and each failure step, take the same time;
`POST /auth/login` is async and waits out the padding on the event loop, so failed sign-ins
hold no worker thread),
and counts towards lockout per typed name, per client IP and per directory identity (several
typed names for one entry share its lockout; a locked identity is refused before the user
bind). The reason (`not_found`, `ambiguous`, `bad_password`, `bind_refused:<result>`,
`no_group`, `empty_password`, `locked`, `identity_mismatch`, `local_name_conflict`,
`unreachable`, ...) is only in `auth_events`. A directory outage is audited but not counted
(shared client IPs would otherwise lock the local admins out too). Passwords with control
characters or failing SASLprep (RFC 4013) are refused before any connection, and counted.

- TLS: `ldaps://` or `ldap://` with `start_tls`; plain LDAP is refused in the settings and
  again before any bind. The certificate must chain to the uploaded CA bundle (only that bundle
  is trusted) and match the server's host name; TLS 1.2 or later.
- Servers are tried in order, starting from the one that answered last; only network and
  TLS failures move to the next one. Any bind result is an answer (a user bind refusal fails
  the sign-in, a service bind refusal makes the directory unavailable). A server that stops at
  its size limit counts as more than one entry.
- Groups: `member_of` reads the user's `memberOf`; `member` searches `group_search_base` for
  `(member=<user DN>)`, and with `nested_groups` follows groups in groups (8 levels, 1000
  groups); `ad_nested` asks Active Directory with `LDAP_MATCHING_RULE_IN_CHAIN`
  (mock-tested only: OpenLDAP has no such rule). DNs compare case-insensitively.
- The local row: `source = 'ldap'`, no password hash, user name from `username_attribute`
  (lower case; `userPrincipalName` values may contain `@`), display name from
  `display_name_attribute`, and `directory_id`: the entry's `entryUUID` (OpenLDAP),
  `objectGUID` (AD) or else its DN, bound at first sign-in. A later sign-in to that row from an
  entry with another identity (a deleted and re-created entry reusing the name) is refused
  (`identity_mismatch`). Created at first sign-in; role updated at every sign-in, and a
  changed role revokes the user's sessions and tokens (`role_change`, actor `ldap`). A directory
  name equal to a local account is refused (never merged). Directory users cannot create API
  tokens (a token would keep its role for up to 90 days without a group check), have no local
  password to change, and their role cannot be set by hand. `parsemaxxing admin reset` only
  resets local accounts, and "keep one active admin" counts local admins only.
- MFA: directory users may enrol TOTP (re-entering the directory password); `require_mfa`
  makes it required for every directory user, and "require MFA for admins" covers directory
  admins too.
- Directory users' sessions end after `ldap.session_max_hours` (12, at most 24) or the auth
  absolute timeout, whichever is shorter, so a group removal takes effect then at the latest.
  Turning LDAP off, or changing the servers or the CA bundle, revokes every directory user's
  sessions.

### Settings (`ldap` group, platform)
`enabled` (off), `servers` (list of `{url, start_tls}`, at most 10), `bind_dn`,
`bind_password` (vault), `ca_bundle` (vault; PEM is not secret but is integrity-protected),
`user_search_base`, `user_filter` (`(uid={username})`; one filter, `{username}` 1 to 4
times), `username_attribute` (`uid`), `display_name_attribute` (`displayName`), `group_mode`
(`member_of` | `member` | `ad_nested`), `group_search_base`, `nested_groups` (off),
`group_roles` (`{group DN: "viewer" | "admin"}`), `connect_timeout_seconds` (5),
`read_timeout_seconds` (10), `page_size` (500), `require_mfa` (off), `session_max_hours` (12). Turning `enabled` on needs
servers, the CA bundle, bind DN and password, the user search base, the group base (except in
`member_of` mode) and at least one mapping.

### Admin routes (session only)
| Route | Body | Returns |
| --- | --- | --- |
| `GET /auth/ldap` | | `settings` (every non-secret field), `bind_password_set`, `ca_bundle` (`[{subject, issuer, not_after, sha256}]` or null), `sources`, `version`, `missing_for_enable`, `local_admins` |
| `PUT /auth/ldap` | `{settings?: {field: value}, bind_password?: str, current_password?: str, expected_version?: int}` | as GET. Secret fields are refused in `settings`; the bind password is write-only. When `settings.servers` differs from the stored list, `bind_password` and the admin's own `current_password` are required (422, then 403 for a wrong current password) |
| `POST /auth/ldap/ca-bundle` | `{pem, bind_password, current_password, expected_version?}` (certificates only, CA, unexpired, at most 256 KB) | as GET |
| `POST /auth/ldap/test-connection` | | `{ok, servers: [{url, ok, steps: [{step: connect, tls, certificate or bind, ok, detail, certificate_info?}]}]}` |
| `POST /auth/ldap/test-user-lookup` | `{username}` | `{ok, found, dn, matched_groups, role, message}`: never another attribute or a password |

The stored bind password never goes to a new endpoint: changing the servers or the CA bundle
needs it entered again, plus the admin's password (otherwise an admin could repoint the
directory and test-connect to collect the stored password, appsec M1).

Errors: 422 (invalid settings, with the field and rule; "Enter the bind password again when you
change servers or the CA bundle."), 403 (wrong current password, counted like a sign-in
failure), 409 (version conflict; tests before the directory is configured), 503 (the directory
could not answer, with a reason code). Audit: `ldap_settings_change` (field names; the new
server URLs when they change; directory sessions revoked), `ldap_ca_bundle` (certificate
fingerprints), `ldap_test`.

### Revisit: ldap3 and pyasn1
`ldap3` 2.9.1 (2021) is the last release; it imports names pyasn1 0.6 deprecates (warnings
filtered in `engine/tests/conftest.py`), so `pyasn1` is pinned `>=0.6.1,<0.7`. Replace ldap3
with `python-ldap` if pyasn1 0.7 drops those names, or if a CVE in ldap3 or pyasn1 appears.
