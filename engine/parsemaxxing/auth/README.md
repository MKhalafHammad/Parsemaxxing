# auth

Local accounts, sessions, TOTP MFA, API tokens, the route policy registry and the audit table
(design 7.3). LDAP is Phase 14.

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
