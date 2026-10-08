from typer.testing import CliRunner

from brickbuild import __version__
from brickbuild.cli import app
from brickbuild.env import LIBRARY_ENV
from tests.fixtures import shapes

runner = CliRunner()


def test_help_lists_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("library", "mesh", "voxelize", "layout", "ldraw", "build"):
        assert command in result.output


def test_stages_run_one_by_one_match_build(library, tmp_path):
    mesh = tmp_path / "arch.stl"
    shapes.arch().export(mesh)
    staged, built = tmp_path / "staged", tmp_path / "built"
    steps = [
        ["mesh", str(mesh), "-o", str(staged)],
        ["voxelize", str(staged / "arch.mesh.glb"), "--size", "20", "-o", str(staged)],
        ["layout", str(staged / "arch.voxels.npz"), "-o", str(staged)],
        ["ldraw", str(staged / "arch.layout.json"), "-o", str(staged)],
    ]
    for args in steps:
        result = runner.invoke(app, args)
        assert result.exit_code == 0, result.output
    result = runner.invoke(app, ["build", str(mesh), "--size", "20", "-o", str(built)])
    assert result.exit_code == 0, result.output
    assert (staged / "arch.ldr").read_text() == (built / "arch.ldr").read_text()


def test_bad_input_is_a_clean_error(library, tmp_path):
    bad = tmp_path / "model.fbx"
    bad.write_text("not a mesh")
    result = runner.invoke(app, ["build", str(bad), "-o", str(tmp_path)])
    assert result.exit_code == 1
    assert "unsupported mesh format" in result.output


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
