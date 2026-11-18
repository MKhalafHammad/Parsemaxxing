#!/usr/bin/env bash
# SBOM and vulnerability scan of the two images this repo builds (engine, web).
#   scripts/image_check.sh sbom   CycloneDX JSON per image in sbom/ (syft)   = make sbom
#   scripts/image_check.sh scan   Trivy: fails on HIGH or CRITICAL with a fix available,
#                                 except entries in .trivyignore (each with a reason and a
#                                 review date)                               = make scan
# The tools run from images pinned by digest and read each image from a `docker save` archive,
# so no container gets the Docker socket. Build the images first (make up, or docker compose
# build engine web). Set DOCKER="sudo docker" if your user cannot reach the Docker socket.
set -euo pipefail
cd "$(dirname "$0")/.."
DOCKER=${DOCKER:-docker}
SYFT=ghcr.io/anchore/syft:v1.55.0@sha256:4cc92b64ca74ffca4c94d4c8fcc01f217731375300be14d0b6eeb2e82eaa110a
TRIVY=ghcr.io/aquasecurity/trivy:0.76.1@sha256:790fd66d1697395d8693d1acaa1ea702406a20f109b6fc7bac8db623eca6c06c
IMAGES="engine web"
mode=${1:-}
[ "$mode" = sbom ] || [ "$mode" = scan ] || { echo "usage: $0 sbom|scan" >&2; exit 2; }

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
chmod 755 "$work" # the tool containers run as their own users
umask 022
[ "$mode" = sbom ] && mkdir -p sbom
status=0
for name in $IMAGES; do
  $DOCKER save -o "$work/$name.tar" "parsemaxxing-$name:local"
  chmod 644 "$work/$name.tar"
  if [ "$mode" = sbom ]; then
    out="sbom/parsemaxxing-$name.cdx.json"
    $DOCKER run --rm --network none -v "$work:/in:ro" "$SYFT" \
      "docker-archive:/in/$name.tar" -o cyclonedx-json --quiet > "$out.partial"
    mv "$out.partial" "$out"
    echo "$out"
  else
    $DOCKER run --rm -v "$work:/in:ro" -v "$PWD/.trivyignore:/trivyignore:ro" "$TRIVY" image \
      --input "/in/$name.tar" --severity HIGH,CRITICAL --ignore-unfixed --exit-code 1 \
      --ignorefile /trivyignore --no-progress --quiet || status=1
  fi
done
exit $status
