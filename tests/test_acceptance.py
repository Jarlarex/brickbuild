"""Phase 1 acceptance: the sphere, cube and arch fixtures each give a valid .ldr
with zero overlapping bricks.

The overlap check here does not use the grid code. It reads each part line,
places the real part body from the LDraw library with that line's matrix and
position, and checks all pairs of bodies for overlap in LDraw space.
"""

import numpy as np
import pytest
from typer.testing import CliRunner

from brickbuild.brick import occupancy
from brickbuild.cli import app
from brickbuild.colours import load_ldconfig
from brickbuild.ldraw import STUD_PRIMITIVES, read_model
from brickbuild.voxel import VoxelGrid
from tests.fixtures.shapes import write_fixtures
from tests.test_layout import expected_cells

FIXTURES = ["sphere", "cube", "arch"]
runner = CliRunner()


@pytest.fixture(scope="module")
def built(tmp_path_factory, library):
    out = tmp_path_factory.mktemp("acceptance")
    results = {}
    for name, mesh in write_fixtures(out / "meshes").items():
        result = runner.invoke(app, ["build", str(mesh), "--out", str(out), "--size", "32"])
        assert result.exit_code == 0, result.output
        results[name] = {
            "ldr": out / f"{name}.ldr",
            "voxels": out / f"{name}.voxels.npz",
            "output": result.output,
        }
    return results


def part_lines(path):
    lines = []
    for line in path.read_text().splitlines():
        tok = line.split()
        if tok and tok[0] == "1":
            vals = np.array(tok[2:14], dtype=float)
            lines.append((int(tok[1]), vals[:3], vals[3:].reshape(3, 3), " ".join(tok[14:])))
    return lines


@pytest.mark.parametrize("name", FIXTURES)
def test_every_line_is_valid_ldraw(built, library, name):
    path = built[name]["ldr"]
    text = path.read_text().splitlines()
    assert text[0] == f"0 {name}"
    assert text[1] == f"0 Name: {path.name}"
    known_colours = {c.code for c in load_ldconfig(library.ldconfig_path)}
    lines = part_lines(path)
    assert lines
    for colour, _position, matrix, part in lines:
        assert library.resolve(part).is_file()
        assert colour in known_colours
        np.testing.assert_allclose(matrix @ matrix.T, np.eye(3), atol=1e-9)
        assert np.linalg.det(matrix) == pytest.approx(1.0)


@pytest.mark.parametrize("name", FIXTURES)
def test_no_two_bricks_overlap_in_ldraw_space(built, library, name):
    lines = part_lines(built[name]["ldr"])
    lo, hi = [], []
    for _colour, position, matrix, part in lines:
        body = library.points(part, STUD_PRIMITIVES) @ matrix.T + position
        lo.append(body.min(axis=0))
        hi.append(body.max(axis=0))
    lo, hi = np.array(lo), np.array(hi)
    overlapping = 0
    for start in range(0, len(lo), 256):
        a_lo, a_hi = lo[start : start + 256, None, :], hi[start : start + 256, None, :]
        depth = np.minimum(a_hi, hi[None]) - np.maximum(a_lo, lo[None])
        hits = (depth > 1e-6).all(axis=2)
        rows = np.arange(start, start + len(hits))
        hits[np.arange(len(hits)), rows] = False  # a brick does not overlap itself
        overlapping += int(hits.sum())
    assert overlapping == 0


@pytest.mark.parametrize("name", FIXTURES)
def test_model_covers_exactly_the_voxels_and_stands_on_the_ground(built, name):
    bricks = read_model(built[name]["ldr"])
    grid = VoxelGrid.load(built[name]["voxels"])
    counts = occupancy(bricks)
    assert set(counts.values()) == {1}
    assert set(counts) == set(expected_cells(grid))
    assert min(b.y for b in bricks) == 0


def test_arch_keeps_its_opening(built):
    bricks = read_model(built["arch"]["ldr"])
    ground = [b for b in bricks if b.y == 0]
    xs = sorted({x for b in ground for x in range(b.x, b.x + b.w)})
    assert xs[0] == 0 and xs[-1] == 31
    assert not set(range(12, 20)) & set(xs), "no bricks on the ground under the arch"


@pytest.mark.parametrize("name", FIXTURES)
def test_build_reports_counts_and_unchecked_stability(built, name):
    output = built[name]["output"]
    assert "total," in output and "distinct parts" in output
    assert "stability: NOT CHECKED" in output
