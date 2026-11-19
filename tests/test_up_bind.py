"""scripts/up.sh: refuses a non-loopback HTTPS_BIND until Phases 12 to 14 are reviewed and merged (finding M3), and
goes on without LLM_API_KEY in .env (init_env.py exit 2), since the vault may hold it.

Runs a copy of up.sh in a temporary repo whose init_env.py and make_secrets.py are stubs that
stop the script, so nothing reaches Docker.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

UP = Path(__file__).resolve().parents[1] / "scripts" / "up.sh"


def run(
    tmp_path: Path, env_file: str, init_rc: int = 7, **env: str
) -> subprocess.CompletedProcess[str]:
    (tmp_path / "scripts").mkdir(exist_ok=True)
    shutil.copy(UP, tmp_path / "scripts" / "up.sh")
    (tmp_path / "scripts" / "init_env.py").write_text(
        f"import sys; sys.exit({init_rc})\n"
    )
    (tmp_path / "scripts" / "make_secrets.py").write_text("import sys; sys.exit(9)\n")
    (tmp_path / ".env").write_text(env_file)
    base = {k: v for k, v in os.environ.items() if k not in ("HTTPS_BIND", "SUDO_USER")}
    base.pop("PMX_ALLOW_UNAUTHENTICATED_NETWORK", None)
    return subprocess.run(
        ["bash", str(tmp_path / "scripts" / "up.sh")],
        env={**base, **env},
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("bind", ["0.0.0.0", "192.0.2.10", "'0.0.0.0'", "::"])
def test_non_loopback_bind_in_env_file_is_refused(tmp_path: Path, bind: str) -> None:
    r = run(tmp_path, f"HTTPS_BIND={bind}\n")
    assert r.returncode == 1 and "refused" in r.stderr and "Phases 12 to 14" in r.stderr


def test_environment_overrides_env_file(tmp_path: Path) -> None:
    r = run(tmp_path, "HTTPS_BIND=127.0.0.1\n", HTTPS_BIND="0.0.0.0")
    assert r.returncode == 1 and "refused" in r.stderr


@pytest.mark.parametrize("bind", ["", "127.0.0.1", "::1", "localhost"])
def test_loopback_bind_passes(tmp_path: Path, bind: str) -> None:
    r = run(tmp_path, f"HTTPS_BIND={bind}\n")
    assert r.returncode == 7 and "refused" not in r.stderr  # reached the init_env stub


def test_explicit_opt_in_passes_with_a_warning(tmp_path: Path) -> None:
    r = run(tmp_path, "HTTPS_BIND=0.0.0.0\n", PMX_ALLOW_UNAUTHENTICATED_NETWORK="yes")
    assert r.returncode == 7 and "warning" in r.stderr


def test_missing_llm_key_warns_and_goes_on(tmp_path: Path) -> None:
    r = run(tmp_path, "", init_rc=2)
    assert (
        r.returncode == 9 and "vault" in r.stderr
    )  # reached make_secrets after the warning


def test_other_init_env_errors_stop(tmp_path: Path) -> None:
    r = run(tmp_path, "", init_rc=1)
    assert r.returncode == 1 and "vault" not in r.stderr
