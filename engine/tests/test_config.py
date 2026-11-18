"""Old PARSEWRIGHT_* variables are refused, never silently ignored or used as a fallback."""

import pytest

from parsemaxxing.config import load_env_file


def test_old_variable_in_the_environment_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("PARSEWRIGHT_TEST_INDEX", "pw_test")
    with pytest.raises(RuntimeError) as err:
        load_env_file(tmp_path / "missing.env")  # checked even without a .env file
    assert "PARSEWRIGHT_TEST_INDEX" in str(err.value)
    assert "rename it to PARSEMAXXING_TEST_INDEX" in str(err.value)
    assert "pw_test" not in str(err.value)  # never echo values


@pytest.mark.parametrize("line", ["PARSEWRIGHT_RUNS_DIR=/srv/runs", "  PARSEWRIGHT_RUNS_DIR =x"])
def test_old_variable_in_the_env_file_is_refused(tmp_path, monkeypatch, line):
    monkeypatch.delenv("PARSEMAXXING_RUNS_DIR", raising=False)
    env = tmp_path / ".env"
    env.write_text(f"LLM_MODEL=m\n{line}\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="rename it to PARSEMAXXING_RUNS_DIR"):
        load_env_file(env)


def test_new_names_and_comments_load(tmp_path, monkeypatch):
    monkeypatch.delenv("PARSEMAXXING_TEST_INDEX", raising=False)
    env = tmp_path / ".env"
    env.write_text("# PARSEWRIGHT_TEST_INDEX was the old name\nPARSEMAXXING_TEST_INDEX=pmx_t\n")
    load_env_file(env)
    import os

    assert os.environ["PARSEMAXXING_TEST_INDEX"] == "pmx_t"
