#!/usr/bin/env bash
# One-command stack for judges and local use (`make up`):
#   1. .env: created from .env.example if missing, placeholder passwords generated; secrets/
#      (KEK and database passwords, scripts/make_secrets.py) created if missing;
#   2. Splunk and PostgreSQL started and healthy;
#   3. Splunk prepared (scripts/splunk_bootstrap.py, inside the container): test index, roles,
#      users, the CIM add-on and its index macros, and fresh service tokens written to .env;
#   4. migrations, the engine and the web UI started, and the engine healthy.
# No secret is printed. Set DOCKER="sudo docker" if your user cannot reach the Docker socket.
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -n "${SUDO_USER:-}" ]; then # as root, .env would end up owned by root
  echo 'Run this without sudo. If Docker needs sudo: DOCKER="sudo docker" make up' >&2
  exit 1
fi
DOCKER=${DOCKER:-docker}
compose() { $DOCKER compose "$@"; }

# Login exists (Phase 13), but nothing goes beyond localhost before the Phase 14 hardening
# (LDAP, build-plan): the https proxy stays on loopback unless the admin opts in (M3).
bind=${HTTPS_BIND-$(grep -sE '^HTTPS_BIND=' .env | tail -n1 | cut -d= -f2- | tr -d "\"' " || true)}
case "$bind" in
  "" | 127.0.0.1 | ::1 | "[::1]" | localhost) ;;
  *)
    if [ "${PMX_ALLOW_UNAUTHENTICATED_NETWORK:-}" != yes ]; then
      echo "refused: HTTPS_BIND=$bind would expose the UI beyond this machine. Login is built, but" >&2
      echo "  exposure beyond localhost waits for the Phase 14 hardening (LDAP, docs/build-plan.md)." >&2
      echo "  Use 127.0.0.1, or set PMX_ALLOW_UNAUTHENTICATED_NETWORK=yes to accept the risk." >&2
      exit 1
    fi
    echo "warning: HTTPS_BIND=$bind exposes the UI before the Phase 14 hardening (PMX_ALLOW_UNAUTHENTICATED_NETWORK=yes)" >&2
    ;;
esac

health() { # service -> healthy|starting|unhealthy|exited|missing
  local id
  id=$(compose ps -q "$1" 2>/dev/null || true)
  [ -n "$id" ] || { echo missing; return; }
  $DOCKER inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$id"
}

wait_healthy() { # service, seconds
  local s i
  for ((i = 0; i < $2; i += 5)); do
    s=$(health "$1")
    [ "$s" = healthy ] && return 0
    [ "$s" = running ] && return 0 # no healthcheck defined: readiness is checked later
    [ "$s" = exited ] && break # "unhealthy" can clear: Splunk is slow to start and restart
    sleep 5
  done
  echo "$1 is not healthy ($(health "$1")): see '$DOCKER compose logs $1'" >&2
  return 1
}

rc=0
python3 scripts/init_env.py || rc=$?
case $rc in
  0) ;;
  2) # the key may live in the vault (`parsemaxxing settings import-env`) instead of .env
    echo "warning: LLM_API_KEY not set in .env: the engine will use the vault value; runs fail if the vault has none either" >&2 ;;
  *) exit "$rc" ;;
esac
DOCKER="$DOCKER" python3 scripts/make_secrets.py
DOCKER="$DOCKER" scripts/migrate_v1_volumes.sh # v1 (parsewright_*) volumes; no-op otherwise

echo "starting Splunk and PostgreSQL (Splunk's first start takes a few minutes)"
compose up -d splunk postgres
wait_healthy postgres 120
wait_healthy splunk 900

echo "preparing Splunk"
TEST_INDEX=$(grep -E '^PARSEMAXXING_TEST_INDEX=' .env | cut -d= -f2- || true)
# The script reaches splunkd on the container's loopback; its stdout is the tokens, which go
# straight into .env and never to the terminal.
tokens=$(compose exec -T -e PMX_TEST_INDEX="${TEST_INDEX:-pmx_test}" splunk \
  sh -c 'if command -v python3 >/dev/null; then exec python3 -; else exec /opt/splunk/bin/splunk cmd python3 -; fi' \
  < scripts/splunk_bootstrap.py)
printf '%s\n' "$tokens" | python3 scripts/env_set.py
unset tokens
wait_healthy splunk 300 # the CIM install restarts splunkd, and the engine depends on its health

echo "starting the engine and the web UI"
compose up -d --build
wait_healthy engine 300

# First run: no admin yet. The token is printed only by `make setup-token`, to the terminal.
setup_needed=$(compose exec -T engine python -I -c "import json, urllib.request; print(json.load(urllib.request.urlopen('http://127.0.0.1:8080/setup', timeout=10))['needed'])" 2>/dev/null || true)

WEB_PORT=$(grep -E '^WEB_PORT=' .env | cut -d= -f2- || true)
SPLUNK_WEB_PORT=$(grep -E '^SPLUNK_WEB_PORT=' .env | cut -d= -f2- || true)
cat <<EOF

Parsemaxxing is up.
  UI:          http://localhost:${WEB_PORT:-3000}
  Splunk Web:  http://localhost:${SPLUNK_WEB_PORT:-8000}  (user admin, password SPLUNK_PASSWORD in .env)
First run:     make first-run
EOF
if [ "$setup_needed" = True ]; then
  cat <<EOF

Setup needed: no admin account exists yet.
  1. make setup-token   (prints a one-time token, valid 60 minutes)
  2. open http://localhost:${WEB_PORT:-3000} and create the first admin with that token
EOF
fi
