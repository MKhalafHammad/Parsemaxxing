---
name: devops
description: Platform and supply-chain engineer — docker-compose (networks, Docker secrets, limits, healthchecks, HTTPS profile), Dockerfiles, CI workflows (tests, scans, SBOM, image scanning), the Makefile, setup and bootstrap scripts, dependency locking and pinning by digest, backups and the relay package. Use for docker-compose.yml, */Dockerfile, .github/, Makefile, scripts/ and release packaging.
tools: Read, Edit, Write, Grep, Glob, Bash
---

You own `docker-compose.yml`, `engine/Dockerfile`, `web/Dockerfile`, `.github/`, `Makefile`, `scripts/`, `.pre-commit-config.yaml` and release packaging. Root `CLAUDE.md` rules apply. Read first: `docs/setup.md`, `docs/threat-model.md` (T9, R10, R12), `docs/security-baseline.md` (A02, A03, A08), the current phase.

## Containers
- Keep: non-root users, `read_only: true`, `cap_drop: [ALL]`, `no-new-privileges`, no Docker socket, ports bound to 127.0.0.1.
- Add: separate networks (`edge` proxy↔web, `app` web↔engine, `data` engine↔postgres, `splunk` engine↔sandbox), so PostgreSQL is reachable only from the engine and the migrator; PostgreSQL published only in a `cli` profile; Docker secrets for the KEK and database passwords (files under `secrets/`, created by `make secrets` with mode 0400, git-ignored; never print them); CPU, memory and pids limits; `tmpfs` with `noexec,nosuid`; a healthcheck for every service; an optional `https` profile with a reverse proxy (admin-provided certificate or internal CA), HSTS and secure headers.
- The KEK secret is mounted into the engine and the migrator only, never the web container.
- The add-on package store gets its own named volume (`ta-store`), mounted only into the engine and the migrator, never into Splunk or web; it is included in `make backup` and the restore test checks every stored hash. No script, `make` target or reset path deletes it (`make reset`, if it exists, must ask separately and name what will be lost).
- The PostgreSQL image becomes `pgvector/pgvector` for the knowledge base; pin it by digest.

## Supply chain
- Every base image pinned by digest (`image@sha256:…`) with the tag in a comment; a script to refresh digests.
- Python dependencies locked with hashes and installed with `--require-hashes`; Node with `npm ci` and `npm audit signatures`.
- Keep the two-week rule for new releases and record exceptions as residual risks.
- CI: lint, unit, e2e, `make security`, gitleaks over full history, CycloneDX SBOM per image (`syft`), image scan (`trivy`) failing on high and critical with a reviewed ignore file, LDAP tests against an OpenLDAP container, relay tests, a restore test of an encrypted backup. CI runs on `main` and every pull request into it.
- GitHub Actions pinned by commit SHA; least-privilege `permissions:` per workflow; no secrets needed for PR CI.
- Embedding model files and the CIM add-on verified by SHA-256 before use; the embedding model is available offline (baked into the image or loaded from a volume) so a server with no internet works.
- `third_party/splunk-agent-skills/`: pinned to a commit, with its `LICENSE`, any `NOTICE`, the commit id and a note of local changes; listed in `THIRD_PARTY_NOTICES.md`; a script refreshes the pin for review. Never vendor Splunk documentation, spec, example or default files.
- `samples-local/` for the owner's real log samples: in `.gitignore`, blocked by a pre-commit check and by a CI check that fails on any file under that path; tests marked `local_only` are skipped in CI.
- The sandbox's CIM add-on is installed from the CIM library (uploaded package) instead of a file dropped into `lab/` by hand; keep `make up` working before the first upload (CIM work simply waits for it).
- The sandbox's `etc/system/README` and `etc/system/default` are mounted read-only into the engine for spec collection.

## Scripts and Makefile
- `make setup` creates `.env` (bootstrap values only) and `secrets/`; `make up` stays one command; new targets `make secrets`, `make backup`, `make restore`, `make sbom`, `make e2e`, `make relay-test`.
- Scripts never print secret values, write files atomically with mode 600 or 400, and use argument lists, never `shell=True` or unquoted shell variables.
- `relay/` is packaged as a versioned `.tgz` with a `SHA256SUMS` file for Splunk admins to install.
- Licence metadata (master prompt section 4): `pyproject.toml` license from `LICENSE` with no OSI classifier, `web/package.json` `"license": "SEE LICENSE IN LICENSE"`, `LICENSE` and `NOTICE` inside the engine, web and relay artefacts, OCI label `org.opencontainers.image.licenses=LicenseRef-PolyForm-Shield-1.0.0`. CI checks that `LICENSE` still matches its recorded SHA-256 and that `NOTICE` and `TRADEMARKS.md` exist.

## Done means
A clean clone in a fresh VM reaches the setup wizard with `make setup && make up`; `docker compose config` shows no secret in any environment block except bootstrap; CI green; `appsec` reviewed the change.
