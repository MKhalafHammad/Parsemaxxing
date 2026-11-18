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
- Runtime guardrails are described in [docs/design.md](docs/design.md), section "Guardrails and security", and the threat model in [docs/threat-model.md](docs/threat-model.md).

## Real log retention

Planned (Phase 21, design 7.19); today the platform deletes nothing on a schedule, so use synthetic logs or remove real samples yourself.

- **Deleted:** real samples (uploaded or pulled from Splunk), their copies in the sandbox's `pmx_` test index, raw lines in evidence, approval reports, drift bundles and console transcripts, and masking maps. They go 30 days after the job ends by default; an admin can shorten this per client down to 0 days. No setting allows more than 30 days.
- **Kept:** job metadata, ledger events, check results and numbers, add-on versions and packages, fix memory (configs and check messages only), and each version's masked regression set.
- **Backups:** do not keep backups longer than 30 days, for the same reason.

## Licence

Parsemaxxing is source-available, not open source. Versions up to and including v1.0.0 (released as Parsewright) are under the MIT License and stay that way. Everything after v1.0.0, including v2, is under the [PolyForm Shield License 1.0.0](LICENSE): you may use, change and run it for any purpose, including inside your company or as an MSSP serving your own clients, but not to offer a product or service that competes with it, paid or free. Add-ons it generates for you are yours. The name and logo are covered by [TRADEMARKS.md](TRADEMARKS.md), and third-party components keep their own licences ([THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)).
