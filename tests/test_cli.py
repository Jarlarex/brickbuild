from typer.testing import CliRunner

from brickbuild import __version__
from brickbuild.cli import app
from brickbuild.env import LIBRARY_ENV

runner = CliRunner()


def test_help_lists_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "library" in result.output


def test_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_library_reports_3001_origin(library):
    result = runner.invoke(app, ["library", "--part", "3001"])
    assert result.exit_code == 0, result.output
    assert "Brick  2 x  4" in result.output
    assert "origin is the centre of the top face of the body" in result.output


def test_library_missing_is_a_clear_error(monkeypatch, tmp_path):
    monkeypatch.delenv(LIBRARY_ENV, raising=False)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["library"])
    assert result.exit_code == 1
    assert LIBRARY_ENV in result.output
