"""Create secrets/ and every missing Docker secret file (`make secrets`); never overwrite one.

  secrets/pmx_kek                32 random bytes, base64, one line (the vault's KEK)
  secrets/postgres_password      the database owner's password
  secrets/postgres_app_password  the engine role's password (parsemaxxing_app)
  secrets/pmx_proxy_hop          32 random bytes, base64: the https proxy's X-Pmx-Hop header, so
                                 the web container trusts X-Forwarded-For only from the proxy

The two passwords are taken from .env (POSTGRES_PASSWORD, POSTGRES_APP_PASSWORD) when set there,
so an existing database volume keeps working; otherwise they are generated. Files have no
trailing newline; readers strip whitespace anyway.

Docker bind-mounts file secrets with their host owner and mode, so each file is made 0400 and
owned by its reader (uid 10001, engine/Dockerfile; pmx_proxy_hop: uid 1000, the web image's
"node", also read by the https proxy, which runs as root) through a throwaway container: after
that, your own user cannot read it (use `sudo cat` to back up the KEK). Never prints a
secret. Set DOCKER="sudo docker" if your user cannot reach the Docker socket.

Usage: python3 scripts/make_secrets.py
"""

import base64
import os
import re
import secrets
import shlex
import string
import subprocess  # nosec B404: fixed argument lists only
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIR, ENV = ROOT / "secrets", ROOT / ".env"
UID = 10001  # the engine image's user; postgres reads as root before dropping to its own user
# The web image's "node" user; Caddy reads it as root with DAC_READ_SEARCH, so one file serves both.
OWNER = {"pmx_proxy_hop": 1000}
# The stack's own pinned PostgreSQL image (scripts/refresh_digests.py), so no extra pull.
IMAGE = "postgres:17.11-alpine@sha256:e5d2edd28b1f8d40a0a6c0c9cdc545b19b56a0d5d88f94bc11a97d970d4700d0"
FROM_ENV = {  # nosec B105: variable names, not values
    "postgres_password": "POSTGRES_PASSWORD",
    "postgres_app_password": "POSTGRES_APP_PASSWORD",
}
NAMES = ("pmx_kek", "postgres_password", "postgres_app_password", "pmx_proxy_hop")
# Base64 of 32 random bytes; the others are passwords.
RANDOM = {"pmx_kek", "pmx_proxy_hop"}
PLACEHOLDER = re.compile(r"^(changeme|your-).*")


def kek() -> str:
    return base64.b64encode(secrets.token_bytes(32)).decode()


def password() -> (
    str
):  # letters and digits: still interpolated into URLs until config reads *_FILE
    return "".join(
        secrets.choice(string.ascii_letters + string.digits) for _ in range(32)
    )


def env_values() -> dict[str, str]:
    if not ENV.is_file():
        return {}
    lines = ENV.read_text().splitlines()
    return {
        k.strip(): v.strip() for k, s, v in (ln.partition("=") for ln in lines) if s
    }


def create(path: Path, value: str) -> None:
    """Write `path` atomically with mode 0400; fails if it already exists (no overwrite race)."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".new.")  # created 0600
    try:
        with os.fdopen(fd, "w") as f:
            f.write(value)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o400)
        os.link(tmp, path)
    finally:
        os.unlink(tmp)


def main() -> int:
    os.umask(0o077)
    DIR.mkdir(mode=0o700, exist_ok=True)
    os.chmod(DIR, 0o700)  # nosemgrep: insecure-file-permissions - owner-only directory
    env = env_values()
    for name in NAMES:
        path = DIR / name
        if os.path.lexists(path):
            if path.is_symlink() or not path.is_file():
                print(
                    f"secrets/{name} is not a regular file: fix it by hand",
                    file=sys.stderr,
                )
                return 1
            continue
        old = env.get(FROM_ENV.get(name, ""), "")
        if old and not PLACEHOLDER.match(old):
            create(path, old)
            print(f"created secrets/{name} from .env {FROM_ENV[name]}")
        else:
            create(path, kek() if name in RANDOM else password())
            print(f"created secrets/{name} (generated)")
    wrong: dict[int, list[str]] = {}
    for n in NAMES:  # only its own files: backup_recipients.txt stays the owner's
        uid, st = OWNER.get(n, UID), (DIR / n).stat()
        if st.st_uid != uid or st.st_mode & 0o777 != 0o400:
            wrong.setdefault(uid, []).append(n)
    docker = shlex.split(os.environ.get("DOCKER", "docker"))
    for uid, names in sorted(wrong.items()):
        targets = [f"/s/{n}" for n in names]
        cmd = [*docker, "run", "--rm", "--network", "none", "--entrypoint", "sh",
               "-v", f"{DIR}:/s", IMAGE, "-c", 'chown "$0" "$@" && chmod 0400 "$@"',
               f"{uid}:{uid}", *targets]  # fmt: skip
        if subprocess.run(cmd, check=False).returncode != 0:  # nosec B603
            print(
                f"could not hand the secret files to uid {uid}: is Docker running?",
                file=sys.stderr,
            )
            return 1
        print(f"secret files owned by uid {uid}, mode 0400: {', '.join(names)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
