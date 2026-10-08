import os
from pathlib import Path

from brickbuild.env import LIBRARY_ENV, load_env


def test_relative_library_path_resolves_against_env_file(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text(f"{LIBRARY_ENV}=vendor/ldraw\n")
    sub = tmp_path / "some" / "folder"
    sub.mkdir(parents=True)
    monkeypatch.delenv(LIBRARY_ENV, raising=False)
    monkeypatch.chdir(sub)
    assert load_env() == tmp_path / ".env"
    assert Path(os.environ[LIBRARY_ENV]) == (tmp_path / "vendor" / "ldraw").resolve()


def test_real_environment_wins_over_env_file(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text(f"{LIBRARY_ENV}=from-file\n")
    monkeypatch.setenv(LIBRARY_ENV, "from-environment")
    monkeypatch.chdir(tmp_path)
    load_env()
    assert os.environ[LIBRARY_ENV] == "from-environment"
