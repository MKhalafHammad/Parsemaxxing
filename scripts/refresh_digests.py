"""Check or refresh every pinned image digest (`make digests`; R12).

Every image this repo runs is written `name:tag@sha256:<digest>` (docker-compose.yml, the
Dockerfiles, scripts/, the CI workflow). This script resolves each `name:tag` in the registry and
shows the digest and build date it points to now; with --write it updates the files for review.
Apply the two-week rule before committing: a digest built less than 14 days ago needs a reason
recorded as a residual risk (docs/threat-model.md), unless it is a security rebuild.

Usage: python3 scripts/refresh_digests.py [--write]
"""

import json
import re
import subprocess  # nosec B404: fixed argument lists only
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = ["docker-compose.yml", "engine/Dockerfile", "web/Dockerfile", ".github/workflows/ci.yml",
         *(f"scripts/{p.name}" for p in sorted((ROOT / "scripts").glob("*.*"))
           if p.suffix in {".sh", ".py"} and p.name != "refresh_digests.py")]  # fmt: skip
PINNED = re.compile(
    r"(?P<ref>[a-z0-9][a-z0-9./_-]*:[A-Za-z0-9._-]+)@(?P<digest>sha256:[0-9a-f]{64})"
)


def resolve(ref: str) -> tuple[str, str]:
    out = subprocess.run(  # nosec B603 B607
        ["docker", "buildx", "imagetools", "inspect", ref, "--format",
         '{"digest": {{json .Manifest.Digest}}, "image": {{json .Image}}}'],
        capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    data = json.loads(out)
    image = data["image"]  # one image, or one per platform
    created = (image if "created" in image else image.get("linux/amd64", {})).get(
        "created", ""
    )
    return data["digest"], created[:10] or "unknown"


def main() -> int:
    write = "--write" in sys.argv[1:]
    seen: dict[str, tuple[str, str]] = {}
    changed = False
    for name in FILES:
        path = ROOT / name
        if not path.is_file():
            continue
        text = path.read_text()
        for m in PINNED.finditer(text):
            if m["ref"] not in seen:
                seen[m["ref"]] = resolve(m["ref"])
                print(f"{m['ref']}: {seen[m['ref']][0]} (built {seen[m['ref']][1]})")
            if seen[m["ref"]][0] != m["digest"]:
                print(f"  {name}: {m['digest']} is outdated")
                changed = True
        if write:
            new = PINNED.sub(lambda m: f"{m['ref']}@{seen[m['ref']][0]}", text)
            if new != text:
                path.write_text(new)
    return 1 if changed and not write else 0


if __name__ == "__main__":
    sys.exit(main())
