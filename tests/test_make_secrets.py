"""scripts/make_secrets.py: the Docker secret files, run on a copy in a temporary repo with a fake
docker (the real one would chown the files to uid 10001)."""

import base64
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "make_secrets.py"
NAMES = ("pmx_kek", "postgres_password", "postgres_app_password")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "scripts").mkdir()
    shutil.copy(SCRIPT, tmp_path / "scripts" / SCRIPT.name)
    fake = tmp_path / "docker"
    fake.write_text('#!/bin/sh\nprintf "%s\\n" "$@" >> "$LOG"\n')
    fake.chmod(0o755)
    return tmp_path


def run(repo: Path) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "DOCKER": str(repo / "docker"),
        "LOG": str(repo / "docker.log"),
    }
    return subprocess.run(
        [sys.executable, str(repo / "scripts" / SCRIPT.name)],
        capture_output=True, text=True, check=False, env=env,
    )  # fmt: skip


def read(repo: Path, name: str) -> str:
    path = repo / "secrets" / name
    path.chmod(0o600)  # the test owns the file (the fake docker did not chown it)
    try:
        return path.read_text()
    finally:
        path.chmod(0o400)


def test_creates_every_secret_private_and_quiet(repo: Path) -> None:
    r = run(repo)
    assert r.returncode == 0, r.stderr
    assert stat.S_IMODE((repo / "secrets").stat().st_mode) == 0o700
    for name in NAMES:
        assert stat.S_IMODE((repo / "secrets" / name).stat().st_mode) == 0o400
        value = read(repo, name)
        assert "\n" not in value and value not in r.stdout + r.stderr
    assert len(base64.b64decode(read(repo, "pmx_kek"), validate=True)) == 32
    assert read(repo, "postgres_password") != read(repo, "postgres_app_password")
    assert not [p for p in (repo / "secrets").iterdir() if p.name.startswith(".")]
    # Ownership is handed to the containers' uid, by argument list, without any secret value.
    log = (repo / "docker.log").read_text()
    assert "10001:10001" in log and "--network\nnone" in log
    assert all(read(repo, n) not in log for n in NAMES)


def test_migrates_env_passwords_and_ignores_placeholders(repo: Path) -> None:
    (repo / ".env").write_text(
        "POSTGRES_PASSWORD=OwnerPassFromV1\nPOSTGRES_APP_PASSWORD=changeme-to-another-long-password\n"  # gitleaks:allow
    )
    r = run(repo)
    assert r.returncode == 0
    assert read(repo, "postgres_password") == "OwnerPassFromV1"
    assert read(
        repo, "postgres_app_password"
    ).isalnum()  # placeholder: generated instead
    assert "OwnerPassFromV1" not in r.stdout + r.stderr


def test_never_overwrites_an_existing_secret(repo: Path) -> None:
    run(repo)
    kek = read(repo, "pmx_kek")
    (repo / ".env").write_text("POSTGRES_PASSWORD=SomethingNew\n")
    assert run(repo).returncode == 0
    assert read(repo, "pmx_kek") == kek
    assert read(repo, "postgres_password") != "SomethingNew"


def test_refuses_a_symlink_in_place_of_a_secret(repo: Path) -> None:
    (repo / "secrets").mkdir(mode=0o700)
    (repo / "secrets" / "pmx_kek").symlink_to(repo / "elsewhere")
    r = run(repo)
    assert r.returncode == 1 and "not a regular file" in r.stderr
    assert not (repo / "elsewhere").exists()
