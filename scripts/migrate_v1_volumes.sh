#!/usr/bin/env bash
# One-time move of a v1 install's data after the product rename: compose volumes
# parsewright_<name> are copied into parsemaxxing_<name>. Run by scripts/up.sh before the stack
# starts; a no-op when there is nothing to move.
#   - migrates only if every new volume with an old counterpart is missing or empty, so a
#     non-empty new volume is never overwritten;
#   - refuses while a container is running on any of the volumes;
#   - backs up each old volume to backups/v1-volumes-<timestamp>/<name>.tar first, and checks it;
#   - copies with ownership and permissions kept, then compares file lists, owners, modes and sizes;
#   - never deletes the old volumes: it prints how to remove them by hand.
# Set DOCKER="sudo docker" if your user cannot reach the Docker socket.
set -euo pipefail
cd "$(dirname "$0")/.."
DOCKER=${DOCKER:-docker}
OLD=parsewright
NEW=parsemaxxing
NAMES="splunk-etc splunk-var pgdata packages runs" # the volumes: block of docker-compose.yml
IMAGE=postgres:17.11-alpine # already pulled for the stack, so no new image

exists() { $DOCKER volume inspect "$1" >/dev/null 2>&1; }
empty() { $DOCKER run --rm -v "$1":/v:ro --entrypoint sh "$IMAGE" -c '[ -z "$(ls -A /v)" ]'; }
listing() { # owner, mode and type of every entry, plus the size of every file
  $DOCKER run --rm -v "$1":/v:ro --entrypoint sh "$IMAGE" -c \
    "cd /v && find . -exec stat -c '%n|%F|%u:%g|%a' {} + | sort && find . -type f -exec stat -c '%n|%s' {} + | sort"
}

todo=""
for n in $NAMES; do
  exists "${OLD}_$n" || continue
  if exists "${NEW}_$n" && ! empty "${NEW}_$n"; then
    echo "note: v1 volumes (${OLD}_*) remain next to ${NEW}_* volumes that hold data, so" >&2
    echo "      nothing was copied. Remove the v1 volumes by hand when you no longer need them." >&2
    exit 0
  fi
  todo="$todo $n"
done
[ -n "$todo" ] || exit 0

for n in $todo; do
  for v in "${OLD}_$n" "${NEW}_$n"; do
    if [ -n "$($DOCKER ps -q --filter "volume=$v")" ]; then
      echo "A running container uses volume $v. Stop the old stack first:" >&2
      echo "  $DOCKER compose -p $OLD down    (without -v, which would delete the data)" >&2
      exit 1
    fi
  done
done

echo "migrating v1 data volumes:$todo"
backup="backups/v1-volumes-$(date +%Y%m%d-%H%M%S)"
umask 077
mkdir -p backups
mkdir "$backup"
for n in $todo; do
  # tar runs in the container (it can read every owner's files) and streams to a host file
  $DOCKER run --rm -v "${OLD}_$n":/v:ro --entrypoint tar "$IMAGE" -C /v -cpf - . > "$backup/$n.tar"
  tar -tf "$backup/$n.tar" >/dev/null || { echo "backup $backup/$n.tar is not readable" >&2; exit 1; }
done
echo "backup written to $backup/"

created=""
rollback() { # remove only the new volumes this run filled; they were missing or empty before
  echo "migration failed; removing the partly filled new volumes:$created" >&2
  for n in $created; do $DOCKER volume rm -f "${NEW}_$n" >/dev/null || true; done
  echo "The v1 volumes and $backup/ are untouched. Fix the error and run 'make up' again." >&2
}
trap rollback ERR
for n in $todo; do
  if ! exists "${NEW}_$n"; then # labelled as compose would, so compose adopts it without a warning
    $DOCKER volume create --label "com.docker.compose.project=$NEW" \
      --label "com.docker.compose.volume=$n" "${NEW}_$n" >/dev/null
  fi
  created="$created $n"
  $DOCKER run --rm -v "${OLD}_$n":/from:ro -v "${NEW}_$n":/to --entrypoint cp "$IMAGE" -a /from/. /to/
  before=$(listing "${OLD}_$n")
  after=$(listing "${NEW}_$n")
  if [ -z "$before" ] || [ "$before" != "$after" ]; then
    echo "copy of ${OLD}_$n differs from the original" >&2
    false
  fi
  echo "  ${OLD}_$n -> ${NEW}_$n: verified"
done
trap - ERR

echo "Migration done. The v1 volumes are kept; once the new stack works, remove them with:"
for n in $todo; do echo "  $DOCKER volume rm ${OLD}_$n"; done
echo "and the backup with: rm -r $backup"
