# Parsemaxxing developer commands. Run `make setup` once after cloning.
.PHONY: setup env secrets up first-run down logs test e2e lint security lock digests sbom scan \
	backup restore restore-test setup-token ldap-test

VENV := .venv
BIN := $(VENV)/bin

setup: secrets
	python3 -m venv $(VENV)
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -e 'engine[dev]'
	$(BIN)/pre-commit install
	cd web && npm ci
	@echo "Back up secrets/pmx_kek away from this server (sudo cat secrets/pmx_kek): without it every stored secret is lost."

# Create .env and generate placeholder passwords (no secret is printed).
env:
	python3 scripts/init_env.py

# .env (as `make env`; exit 2 = LLM key still a placeholder) and the Docker secrets in secrets/:
# the KEK and the database passwords, each 0400 and owned by the containers' uid. Never
# overwrites a file; takes the passwords from .env so an existing database keeps working.
secrets:
	python3 scripts/init_env.py || [ $$? -eq 2 ]
	python3 scripts/make_secrets.py

# The whole stack, Splunk prepared, in one command (scripts/up.sh). DOCKER="sudo docker" if needed.
up:
	scripts/up.sh

# Upload the bundled synthetic sample and follow it to the approval report.
first-run:
	python3 scripts/first_run.py

# While no admin exists: a new one-time setup token from the running engine, to this terminal.
setup-token:
	$(or $(DOCKER),docker) compose exec engine parsemaxxing --env-file /dev/null setup-token

down:
	docker compose down

logs:
	docker compose logs -f

# The OpenLDAP integration tests run in `make ldap-test` (CI job ldap-test), not here.
test:
	$(BIN)/pytest -m "not ldap_integration" engine/tests tests
	$(MAKE) e2e

# Real OpenLDAP in docker (engine/tests/auth/openldap); fails instead of skipping without docker.
# Needs PARSEMAXXING_TEST_DSN set to a throwaway PostgreSQL, as `make test` does.
ldap-test:
	PARSEMAXXING_LDAP_IT=1 $(BIN)/pytest -m ldap_integration engine/tests/auth

e2e:
	cd web && npm run build && npm run test:e2e

lint:
	$(BIN)/pre-commit run --all-files
	cd web && npm run lint && npm run typecheck

# Needs semgrep and gitleaks on PATH (see docs/setup.md, "Running tests and security checks").
security:
	$(BIN)/bandit -c engine/pyproject.toml -r engine scripts
	semgrep scan --config p/default --error --metrics=off --quiet
	$(BIN)/pip-audit --skip-editable
	# Shipped packages only; dev tooling advisories are tracked in threat-model R11.
	cd web && npm audit --audit-level=moderate --omit=dev
	cd web && npm audit signatures
	gitleaks git --redact --verbose .

# Engine runtime dependencies, pinned with hashes, released at least two weeks ago (set the
# date). hatchling, the build backend, is added so the image builds without isolation.
lock:
	echo 'hatchling>=1.32' | uv pip compile engine/pyproject.toml - \
	  --generate-hashes --universal --python-version 3.12 --exclude-newer $(or $(BEFORE),2026-11-04) \
	  -o engine/requirements.lock

# Show where each pinned image tag points now; `make digests WRITE=1` updates the files.
digests:
	python3 scripts/refresh_digests.py $(if $(WRITE),--write)

# CycloneDX SBOM per built image into sbom/; Trivy scan failing on fixable HIGH/CRITICAL.
sbom:
	scripts/image_check.sh sbom
scan:
	scripts/image_check.sh scan

# Encrypted database backup into backups/ (scripts/backup.sh says how to set the age key).
backup:
	scripts/backup.sh
# make restore FILE=backups/pmx-....dump.age IDENTITY=/path/to/pmx-backup.key
restore:
	scripts/restore.sh "$(FILE)" "$(IDENTITY)"
# Backup and restore round trip in a separate compose project (CI job restore-test).
restore-test:
	scripts/restore_test.sh
