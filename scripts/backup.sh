#!/usr/bin/env bash
# Encrypted database backup (`make backup`): pg_dump (custom format) inside the postgres
# container, piped straight into `age` in a throwaway engine-image container with no network,
# written to backups/pmx-<timestamp>.dump.age (directory 0700, file 0600). The plaintext dump
# only ever exists in the pipe.
#
# Recipients: age public keys, one per line, in secrets/backup_recipients.txt (or the file named
# by PMX_BACKUP_RECIPIENTS). Create the key pair away from this server and keep the private key
# there: `age-keygen -o pmx-backup.key` prints the public key to copy here. Without the private
# key a backup cannot be restored. Backups older than 30 days in the backup directory are
# deleted after each new one (design 7.19); only this tool's pmx-*.dump.age files and sidecars.
# Sidecar <file>.sha256 (0600), the engine's format (ledger/backup.py): "<sha256>  <file name>"
# of the encrypted file, then "ledger-head <id>:<hash>", the newest ledger row at backup time
# ("-1:<64 zeros>" if empty). scripts/restore.sh refuses a file that does not match it.
# Not yet covered: the add-on package store (its volume arrives with the CIM/TA library work).
# Set DOCKER="sudo docker" if your user cannot reach the Docker socket.
set -euo pipefail
cd "$(dirname "$0")/.."
DOCKER=${DOCKER:-docker}
IMAGE=parsemaxxing-engine:local # built by `make up`; has age and the PostgreSQL 17 client
recipients_file=${PMX_BACKUP_RECIPIENTS:-secrets/backup_recipients.txt}
out_dir=${PMX_BACKUP_DIR:-backups}

[ -f "$recipients_file" ] || {
  echo "no backup recipients: put an age public key (age1...) in $recipients_file" >&2
  echo "  (make the key pair elsewhere with: age-keygen -o pmx-backup.key)" >&2
  exit 1
}
args=()
while IFS= read -r line || [ -n "$line" ]; do
  line=${line%%#*}
  line=${line//[[:space:]]/}
  [ -n "$line" ] || continue
  [[ $line =~ ^age1[02-9ac-hj-np-z]{58}$ ]] || { echo "not an age public key in $recipients_file" >&2; exit 1; }
  args+=(-r "$line")
done < "$recipients_file"
[ ${#args[@]} -gt 0 ] || { echo "$recipients_file holds no age public key" >&2; exit 1; }

umask 077
mkdir -p "$out_dir"
chmod 700 "$out_dir"
out="$out_dir/pmx-$(date -u +%Y%m%dT%H%M%SZ).dump.age"
tmp="$out.partial"
trap 'rm -f "$tmp" "$out.sha256.partial"' EXIT

# Read before the dump, so the dump holds at least this row.
head_row=$($DOCKER compose exec -T postgres sh -c 'exec psql -qtAX -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -F : -c "SELECT id, hash FROM ledger ORDER BY id DESC LIMIT 1"')
head_row=${head_row:--1:$(printf '0%.0s' {1..64})}
[[ $head_row =~ ^(-1|[0-9]{1,19}):[0-9a-f]{64}$ ]] || { echo "unexpected ledger head" >&2; exit 1; }
# The container's own POSTGRES_USER / POSTGRES_DB, over its local socket: no password needed.
$DOCKER compose exec -T postgres sh -c 'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' \
  | $DOCKER run --rm -i --network none --read-only --cap-drop ALL \
      --security-opt no-new-privileges "$IMAGE" age "${args[@]}" > "$tmp"
[ "$(head -c 21 "$tmp")" = "age-encryption.org/v1" ] || { echo "backup output is not age-encrypted" >&2; exit 1; }
printf '%s  %s\nledger-head %s\n' "$(sha256sum "$tmp" | cut -d' ' -f1)" "${out##*/}" "$head_row" > "$out.sha256.partial"
mv "$out.sha256.partial" "$out.sha256"
mv "$tmp" "$out"
trap - EXIT
echo "backup written to $out (checksum and ledger head in $out.sha256)"
find "$out_dir" -maxdepth 1 -type f \( -name 'pmx-*.dump.age' -o -name 'pmx-*.dump.age.sha256' \) \
  -mtime +30 -print -delete | sed 's/^/pruned (older than 30 days): /'
