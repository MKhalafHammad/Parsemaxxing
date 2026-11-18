#!/usr/bin/env bash
# Encrypted backup and restore round trip (CI job "restore-test"; locally: make restore-test).
# Uses its own compose project (pmx-restore-test), so your stack and its volumes are untouched:
#   migrate a fresh database, add a marker row, back up with a throwaway age key, delete the
#   volume, migrate a new empty database, restore, and compare the marker and the schema.
# Needs .env and secrets/ (make setup) and the engine image (built here if missing).
set -euo pipefail
cd "$(dirname "$0")/.."
DOCKER=${DOCKER:-docker}
export COMPOSE_PROJECT_NAME=pmx-restore-test
compose() { $DOCKER compose "$@"; }
psql_c() { compose exec -T postgres sh -c 'psql -qtAX -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'; }

work=$(mktemp -d)
cleanup() { compose down -v --remove-orphans >/dev/null 2>&1 || true; rm -rf "$work"; }
trap cleanup EXIT

compose build migrate
compose up -d --wait postgres
compose run --rm migrate
marker=$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')
printf 'CREATE TABLE restore_probe (v text); INSERT INTO restore_probe VALUES (%s);\n' "'$marker'" | psql_c
schema_query="SELECT string_agg(table_name, ',' ORDER BY table_name) FROM information_schema.tables WHERE table_schema = 'public';"
before=$(echo "$schema_query" | psql_c)

$DOCKER run --rm --network none parsemaxxing-engine:local age-keygen 2>/dev/null > "$work/key"
$DOCKER run --rm -i --network none parsemaxxing-engine:local age-keygen -y < "$work/key" > "$work/recipients"
PMX_BACKUP_RECIPIENTS="$work/recipients" PMX_BACKUP_DIR="$work/out" scripts/backup.sh
backup=$(ls "$work"/out/*.dump.age)
[ "$(stat -c %a "$work/out")" = 700 ] && [ "$(stat -c %a "$backup")" = 600 ] || { echo "backup permissions are wrong" >&2; exit 1; }
if grep -qa "$marker" "$backup" || grep -qa PGDMP "$backup"; then
  echo "backup is not encrypted" >&2; exit 1
fi

compose down -v
compose up -d --wait postgres
compose run --rm migrate
PMX_RESTORE_YES=1 scripts/restore.sh "$backup" "$work/key"
[ "$(echo 'SELECT v FROM restore_probe;' | psql_c)" = "$marker" ] || { echo "marker row lost" >&2; exit 1; }
[ "$(echo "$schema_query" | psql_c)" = "$before" ] || { echo "schema differs after restore" >&2; exit 1; }
echo "restore test passed: encrypted backup restored into a fresh database"
