import numpy as np
import pytest

from brickbuild.brick import Brick, find_overlaps, load_layout, occupancy, save_layout
from brickbuild.layout.greedy import greedy_layout, merge_order
from brickbuild.parts import PLATES_PER_BRICK
from brickbuild.voxel import EMPTY, VoxelGrid, voxelize
from tests.fixtures import shapes


def expected_cells(grid: VoxelGrid) -> dict[tuple[int, int, int], int]:
    """Plate cells each filled voxel stands for, with the voxel's colour."""
    cells = {}
    for i, j, k in np.argwhere(grid.filled):
        for p in range(PLATES_PER_BRICK):
            cells[(int(i), int(j) * PLATES_PER_BRICK + p, int(k))] = int(grid.colour[i, j, k])
    return cells


def assert_exact_tiling(grid: VoxelGrid, bricks: list[Brick]) -> None:
    assert find_overlaps(bricks) == []
    counts = occupancy(bricks)
    assert set(counts.values()) <= {1}
    wanted = expected_cells(grid)
    assert set(counts) == set(wanted), "bricks cover exactly the filled voxels"
    for brick in bricks:
        brick.validate()
        assert brick.y % PLATES_PER_BRICK == 0
        assert {wanted[c] for c in brick.cells()} == {brick.colour}, "one colour per brick"


def test_merge_order_is_largest_first_and_prefers_two_wide():
    ids = [p.id for p in merge_order()]
    assert ids == ["3007", "2456", "3001", "3008", "3002", "3009",
                   "3003", "3010", "3622", "3004", "3005"]  # fmt: skip


def test_overlap_checker_detects_overlaps():
    a = Brick("3001", 0, 0, 0, 4, 2, 3, 0, 4)
    b = Brick("3003", 3, 0, 1, 2, 2, 3, 0, 4)  # shares cell (3, *, 1)
    c = Brick("3003", 0, 3, 0, 2, 2, 3, 0, 4)  # stacked on top, no overlap
    assert find_overlaps([a, b, c]) == [(0, 1)]


def test_solid_block_uses_large_bricks():
    colour = np.full((8, 1, 2), 15, dtype=np.int32)
    bricks = greedy_layout(VoxelGrid(colour=colour))
    assert [b.part for b in bricks] == ["3007"]


def test_long_axis_alternates_between_layers():
    colour = np.full((8, 2, 8), 15, dtype=np.int32)
    bricks = greedy_layout(VoxelGrid(colour=colour))
    assert {(b.w, b.d) for b in bricks if b.y == 0} == {(8, 2)}
    assert {(b.w, b.d) for b in bricks if b.y == 3} == {(2, 8)}


def test_colours_are_never_merged():
    colour = np.full((4, 1, 2), 1, dtype=np.int32)
    colour[2:, 0, :] = 4
    bricks = greedy_layout(VoxelGrid(colour=colour))
    assert sorted((b.part, b.colour) for b in bricks) == [("3003", 1), ("3003", 4)]


@pytest.mark.parametrize("seed", range(12))
def test_random_grids_are_tiled_exactly(seed):
    rng = np.random.default_rng(seed)
    shape = (int(rng.integers(1, 14)), int(rng.integers(1, 5)), int(rng.integers(1, 14)))
    colour = rng.choice([1, 4, 14], size=shape).astype(np.int32)
    colour[rng.random(shape) < rng.uniform(0, 0.5)] = EMPTY
    grid = VoxelGrid(colour=colour)
    assert_exact_tiling(grid, greedy_layout(grid))


@pytest.mark.parametrize("make", [shapes.cube, shapes.sphere, shapes.arch])
def test_fixtures_are_tiled_exactly(make):
    grid = voxelize(make(), size=32)
    bricks = greedy_layout(grid)
    assert_exact_tiling(grid, bricks)


def test_layout_round_trip(tmp_path):
    grid = voxelize(shapes.arch(), size=16)
    bricks = greedy_layout(grid)
    path = tmp_path / "layout.json"
    save_layout(bricks, path, notes=["hello"])
    loaded, notes = load_layout(path)
    assert loaded == bricks
    assert notes == ["hello"]


def test_layout_rejects_inconsistent_bricks(tmp_path):
    path = tmp_path / "layout.json"
    save_layout([Brick("3001", 0, 0, 0, 2, 2, 3, 0, 4)], path)
    with pytest.raises(ValueError):
        load_layout(path)
