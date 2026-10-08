import numpy as np
import pytest

from brickbuild.brick import Brick
from brickbuild.layout.greedy import greedy_layout
from brickbuild.ldraw import (
    GRID_TO_LDRAW,
    STUD_PRIMITIVES,
    ldraw_to_grid,
    part_line,
    placement,
    read_model,
    write_model,
)
from brickbuild.parts import STARTER_BRICKS
from brickbuild.voxel import voxelize
from tests.fixtures import shapes


def test_grid_to_ldraw_is_a_rotation_not_a_mirror():
    axes = GRID_TO_LDRAW / np.abs(GRID_TO_LDRAW).max(axis=0)
    assert np.linalg.det(axes) == pytest.approx(1.0)
    up = GRID_TO_LDRAW @ [0, 1, 0]
    assert up[1] < 0, "-Y is up in LDraw"


def test_part_lines_for_known_placements():
    # 2x4 on the ground at the origin: body from Y=-24 (top) to Y=0 (ground).
    assert part_line(Brick("3001", 0, 0, 0, 4, 2, 3, 0, 4)) == (
        "1 4 40 -24 -20 1 0 0 0 1 0 0 0 1 3001.dat"
    )
    # One brick higher.
    assert part_line(Brick("3001", 0, 3, 0, 4, 2, 3, 0, 4)) == (
        "1 4 40 -48 -20 1 0 0 0 1 0 0 0 1 3001.dat"
    )
    # Turned 90 degrees: long side along grid z.
    assert part_line(Brick("3001", 0, 0, 0, 2, 4, 3, 90, 1)) == (
        "1 1 20 -24 -40 0 0 1 0 1 0 -1 0 0 3001.dat"
    )


@pytest.mark.parametrize("part", STARTER_BRICKS, ids=lambda p: p.id)
@pytest.mark.parametrize("rot", [0, 90])
def test_placed_part_geometry_fills_exactly_its_cells(library, part, rot):
    """Transform the real part body from the library and compare with the grid cells."""
    w, d = part.footprint(rot)
    brick = Brick(part.id, 3, 6, 5, w, d, part.h, rot, 4)
    position, rotation = placement(brick)
    body = library.points(f"{part.id}.dat", STUD_PRIMITIVES) @ rotation.T + position
    lo = ldraw_to_grid(body.min(axis=0))
    hi = ldraw_to_grid(body.max(axis=0))
    grid_lo, grid_hi = np.minimum(lo, hi), np.maximum(lo, hi)
    np.testing.assert_allclose(grid_lo, [brick.x, brick.y, brick.z], atol=1e-9)
    np.testing.assert_allclose(
        grid_hi, [brick.x + brick.w, brick.y + brick.h, brick.z + brick.d], atol=1e-9
    )


@pytest.mark.parametrize("make", [shapes.cube, shapes.sphere, shapes.arch])
def test_write_then_read_gives_the_same_bricks(tmp_path, make):
    bricks = greedy_layout(voxelize(make(), size=16))
    path = tmp_path / "model.ldr"
    write_model(bricks, path, title="test")
    assert sorted(read_model(path), key=repr) == sorted(bricks, key=repr)


def test_model_file_layout(tmp_path):
    bricks = [
        Brick("3003", 0, 3, 0, 2, 2, 3, 0, 4),
        Brick("3001", 0, 0, 0, 4, 2, 3, 0, 1),
    ]
    path = tmp_path / "tower.ldr"
    write_model(bricks, path, title="Tower")
    lines = path.read_text().splitlines()
    assert lines[:3] == ["0 Tower", "0 Name: tower.ldr", "0 Author: brickbuild"]
    parts = [ln.split()[-1] for ln in lines if ln.startswith("1 ")]
    assert parts == ["3001.dat", "3003.dat"], "bottom layer first"
    assert sum(ln == "0 STEP" for ln in lines) == 2


def test_read_rejects_parts_off_the_grid(tmp_path):
    path = tmp_path / "bad.ldr"
    path.write_text("1 4 45 -24 -20 1 0 0 0 1 0 0 0 1 3001.dat\n")
    with pytest.raises(ValueError, match="stud grid"):
        read_model(path)


def test_read_rejects_unknown_parts_and_tilted_parts(tmp_path):
    unknown = tmp_path / "unknown.ldr"
    unknown.write_text("1 4 0 0 0 1 0 0 0 1 0 0 0 1 3069b.dat\n")
    with pytest.raises(ValueError, match="catalogue"):
        read_model(unknown)
    tilted = tmp_path / "tilted.ldr"
    tilted.write_text("1 4 40 -24 -20 1 0 0 0 0 1 0 -1 0 3001.dat\n")
    with pytest.raises(ValueError, match="upright"):
        read_model(tilted)
