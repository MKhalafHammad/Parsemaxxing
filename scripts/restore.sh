#!/usr/bin/env bash
# Restore an encrypted backup from scripts/backup.sh (`make restore FILE=... IDENTITY=...`).
# REPLACES the current database content. The engine and the web UI are stopped first; run
# `make up` afterwards. On a fresh database volume, start PostgreSQL and run the migrations
# first (`docker compose run --rm migrate`) so the app role exists for the dump's grants.
#
#   scripts/restore.sh backups/pmx-<timestamp>.dump.age /path/to/pmx-backup.key
#
# The age private key is read by a throwaway container with no network, running as your user;
# the decrypted dump only ever exists in the pipe to pg_restore. PMX_RESTORE_YES=1 skips the
# confirmation (CI). Set DOCKER="sudo docker" if your user cannot reach the Docker socket.
set -euo pipefail
cd "$(dirname "$0")/.."
DOCKER=${DOCKER:-docker}
IMAGE=parsemaxxing-engine:local
[ $# -eq 2 ] || { echo "usage: $0 BACKUP_FILE AGE_IDENTITY_FILE" >&2; exit 2; }
file=$(realpath -- "$1")
identity=$(realpath -- "$2")
[ -f "$file" ] && [ -f "$identity" ] || { echo "backup or identity file not found" >&2; exit 1; }
[ "$(head -c 21 "$file")" = "age-encryption.org/v1" ] || { echo "$1 is not an age-encrypted backup" >&2; exit 1; }

if [ "${PMX_RESTORE_YES:-}" != 1 ]; then
  read -r -p "This replaces every row in the Parsemaxxing database. Type RESTORE to go on: " answer
  [ "$answer" = RESTORE ] || { echo "cancelled"; exit 1; }
fi

$DOCKER compose stop engine web >/dev/null 2>&1 || true
$DOCKER run --rm -i --network none --read-only --cap-drop ALL --security-opt no-new-privileges \
    --user "$(id -u):$(id -g)" --mount "type=bind,src=$identity,dst=/run/identity,readonly" \
    "$IMAGE" age -d -i /run/identity < "$file" \
  | $DOCKER compose exec -T postgres sh -c \
      'exec pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --exit-on-error --single-transaction'
echo "restored $1; start the stack again with: make up"
