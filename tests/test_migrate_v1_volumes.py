"""scripts/migrate_v1_volumes.sh decisions (no-op, refusal), run against a fake docker.

The copy itself needs a real Docker daemon and is not exercised here.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "migrate_v1_volumes.sh"

# Volumes in $VOLS exist, those in $NONEMPTY hold data, those in $RUNNING have a running
# container. Every call is logged so a test can assert nothing was copied.
FAKE_DOCKER = """#!/bin/sh
echo "$*" >> "$LOG"
has() { case " $1 " in *" $2 "*) return 0;; esac; return 1; }
case "$1 $2" in
  "volume inspect") has "$VOLS" "$3" ;;
  "ps -q") v=${4#volume=}; has "$RUNNING" "$v" && echo abc123; exit 0 ;;
  "run --rm") v=${4%%:*}; ! has "$NONEMPTY" "$v" ;;
  *) exit 99 ;;
esac
"""


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "scripts").mkdir()
    shutil.copy(SCRIPT, tmp_path / "scripts" / SCRIPT.name)
    fake = tmp_path / "fake-docker"
    fake.write_text(FAKE_DOCKER)
    fake.chmod(0o755)
    return tmp_path


def run(repo: Path, vols: str, nonempty: str = "", running: str = ""):
    env = {
        **os.environ,
        "DOCKER": str(repo / "fake-docker"),
        "LOG": str(repo / "calls.log"),
        "VOLS": vols,
        "NONEMPTY": nonempty,
        "RUNNING": running,
    }
    result = subprocess.run(
        ["bash", str(repo / "scripts" / SCRIPT.name)],
        check=False,
        env=env,
        capture_output=True,
        text=True,
    )
    log = (repo / "calls.log").read_text() if (repo / "calls.log").exists() else ""
    return result, log


def test_no_v1_volumes_is_a_silent_no_op(repo):
    result, log = run(repo, vols="parsemaxxing_pgdata")
    assert result.returncode == 0 and result.stdout == "" and result.stderr == ""
    assert "run " not in log and not (repo / "backups").exists()


def test_non_empty_new_volume_is_never_overwritten(repo):
    result, log = run(
        repo,
        vols="parsewright_pgdata parsewright_runs parsemaxxing_pgdata",
        nonempty="parsewright_pgdata parsemaxxing_pgdata",
    )
    assert result.returncode == 0 and "nothing was copied" in result.stderr
    assert "cp" not in log and "tar" not in log and not (repo / "backups").exists()


def test_running_container_blocks_the_migration(repo):
    result, log = run(repo, vols="parsewright_pgdata", running="parsewright_pgdata")
    assert result.returncode == 1
    assert "compose -p parsewright down" in result.stderr
    assert "cp" not in log and not (repo / "backups").exists()


def test_running_new_stack_blocks_when_its_volume_is_empty(repo):
    result, _ = run(
        repo, vols="parsewright_runs parsemaxxing_runs", running="parsemaxxing_runs"
    )
    assert result.returncode == 1 and not (repo / "backups").exists()
