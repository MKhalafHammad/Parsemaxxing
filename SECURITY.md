# Security policy

## Reporting a vulnerability

Please report vulnerabilities **privately**, not in a public issue, pull request or discussion.

1. Go to the repository's **Security** tab and choose **Report a vulnerability** (GitHub private vulnerability reporting).
2. Describe the issue, the affected component (engine, web, Docker setup, CI), steps to reproduce and the impact you expect.
3. Use synthetic data in your report. Do not include real secrets, real logs, real hostnames or IP addresses.

You can expect an acknowledgement within 5 working days and an update on the fix within 14 days. Please give us a reasonable time to fix the issue before disclosing it publicly.

## Supported versions

Parsemaxxing v2 is under development and has no 2.0.0 release yet. Only the latest commit on the `main` branch is supported; fixes are not backported to v1.0.0 (released as Parsewright) or to pre-release tags.

| Version | Supported |
| --- | --- |
| `main` (latest) | Yes |
| v1.0.0 (Parsewright) and older | No |

## Never post secrets or real logs

- Never open a public issue, pull request or discussion containing API keys, Splunk tokens, passwords, `.env` contents, or real production logs.
- If you accidentally posted a secret, rotate it immediately, then report it privately as above so the content can be removed.
- Reproduce problems with the synthetic generator's logs, not with real data.

## How the project protects secrets

- `.env` is git-ignored; `.env.example` holds placeholders only.
- gitleaks runs on every commit (pre-commit) and over the full git history in CI.
- At runtime, the LLM key and the Splunk tokens can be kept in an encrypted vault (AES-256-GCM under a key-encryption key in a Docker secret, `secrets/pmx_kek`); `docs/setup.md` says how to back up that key. Database backups are encrypted with `age`.
- Passwords are stored as Argon2id hashes; sessions, API tokens (`pmxt_...`), recovery codes and the setup token only as SHA-256 hashes; TOTP secrets only in the vault. No password, token or code is written to logs or the audit log.
- Runtime guardrails are described in [docs/design.md](docs/design.md), section "Guardrails and security", and the threat model in [docs/threat-model.md](docs/threat-model.md).

## Accounts and access

- Built in Phase 13 (in review): local accounts with `viewer` and `admin` roles, TOTP MFA required for admins by default, server-side sessions, API tokens with an expiry of at most 90 days, and an audit log nobody can edit. Every API route needs a session or a token. LDAP is planned (Phase 14).
- There are no default credentials. The first admin is created with a one-time setup token (`make setup-token`).
- Lost access: `parsemaxxing admin reset <user>` on the host (needs the database owner credentials) sets a new password, clears MFA, unlocks the account and revokes its sessions and tokens.
- Do not expose the platform beyond localhost before Phase 14 lands. `make up` refuses a non-loopback `HTTPS_BIND` unless you opt in.

## Real log retention

Planned (Phase 21, design 7.19); today the platform deletes nothing on a schedule, so use synthetic logs or remove real samples yourself.

- **Deleted:** real samples (uploaded or pulled from Splunk), their copies in the sandbox's `pmx_` test index, raw lines in evidence, approval reports, drift bundles and console transcripts, and masking maps. They go 30 days after the job ends by default; an admin can shorten this per client down to 0 days. No setting allows more than 30 days.
- **Kept:** job metadata, ledger events, check results and numbers, add-on versions and packages, fix memory (configs and check messages only), and each version's masked regression set.
- **Backups:** do not keep backups longer than 30 days, for the same reason.

## Licence

Parsemaxxing is source-available, not open source. Versions up to and including v1.0.0 (released as Parsewright) are under the MIT License and stay that way. Everything after v1.0.0, including v2, is under the [PolyForm Shield License 1.0.0](LICENSE): you may use, change and run it for any purpose, including inside your company or as an MSSP serving your own clients, but not to offer a product or service that competes with it, paid or free. Add-ons it generates for you are yours. The name and logo are covered by [TRADEMARKS.md](TRADEMARKS.md), and third-party components keep their own licences ([THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)).
