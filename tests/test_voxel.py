import numpy as np
import pytest
import trimesh

from brickbuild.colours import Palette, parse_ldconfig
from brickbuild.mesh import load_mesh
from brickbuild.voxel import CELL_MM, EMPTY, VoxelGrid, _solid_cells, voxelize
from tests.fixtures import shapes

PALETTE_TEXT = """\
0 // LDraw Solid Colours
0 !COLOUR Blue    CODE  1  VALUE #1E5AA8  EDGE #333333
0 !COLOUR Red     CODE  4  VALUE #B40000  EDGE #333333
0 !COLOUR Yellow  CODE 14  VALUE #FAC80A  EDGE #333333
0 !COLOUR Grey    CODE 71  VALUE #969696  EDGE #333333
"""


@pytest.fixture
def palette():
    return Palette(parse_ldconfig(PALETTE_TEXT))


@pytest.mark.parametrize("make", [shapes.cube, shapes.sphere, shapes.arch])
def test_fixtures_are_closed_and_outward_facing(make):
    mesh = make()
    assert mesh.is_watertight
    assert mesh.is_winding_consistent
    assert mesh.volume > 0


def test_cube_fills_every_cell():
    # The top face diagonal passes exactly through cell centres, so this also
    # checks that rays through a shared edge are counted once.
    grid = voxelize(shapes.cube(), size=32)
    assert grid.shape == (32, 27, 32)  # 256 mm tall = 26.7 brick layers
    assert grid.filled.all()
    assert grid.notes == []


def test_even_odd_rule_handles_shared_edges_too():
    box = shapes.cube(4.0)
    box.apply_translation([2.0, 2.0, 2.0])  # cell units: occupies [0, 4]^3
    solid = _solid_cells(box.triangles, (4, 4, 4), winding_sign=None)
    assert solid.all()


def test_cells_are_one_stud_wide_and_one_brick_tall():
    box = trimesh.creation.box(extents=(80.0, 48.0, 40.0))  # mm, longest side 10 studs
    grid = voxelize(box, size=10)
    assert grid.scale == pytest.approx(1.0)
    assert grid.cell_mm == CELL_MM
    assert grid.shape == (10, 5, 5)
    assert grid.filled.all()


def test_no_layer_above_the_model_is_left_empty():
    # 128 mm = 13.3 brick layers: 13 layers, the 14th centre would be above the top.
    grid = voxelize(shapes.cube(), size=16)
    assert grid.shape == (16, 13, 16)
    assert grid.filled.all()


def test_longest_side_is_scaled_to_size():
    box = trimesh.creation.box(extents=(1.0, 0.5, 2.0))
    grid = voxelize(box, size=20)
    assert grid.shape[2] == 20
    assert grid.shape[0] == 10
    assert grid.scale == pytest.approx(20 * 8.0 / 2.0)


def test_sphere_volume_and_symmetry():
    grid = voxelize(shapes.sphere(), size=32)
    filled = grid.filled
    cell_volume = np.prod(CELL_MM)
    expected = 4 / 3 * np.pi * (16 * 8.0) ** 3
    assert filled.sum() * cell_volume == pytest.approx(expected, rel=0.03)
    assert (filled == filled[::-1, :, :]).all()
    assert (filled == filled[:, :, ::-1]).all()


def test_arch_has_an_opening_and_two_legs():
    grid = voxelize(shapes.arch(), size=32)
    filled = grid.filled.any(axis=2)  # side view, (x, layer)
    middle = filled.shape[0] // 2
    assert not filled[middle, 0:6].any(), "opening under the arch"
    assert filled[middle, 8:12].all(), "crown"
    assert filled[:6, 0].all() and filled[-6:, 0].all(), "both legs on the ground"
    assert not filled[8:-8, 0].any()


def test_overlapping_shells_merge_into_their_union():
    a = trimesh.creation.box(bounds=[[0, 0, 0], [8, 3, 4]])
    b = trimesh.creation.box(bounds=[[4, 0, 0], [12, 3, 4]])
    mesh = trimesh.util.concatenate([a, b])
    grid = voxelize(mesh, size=12, cell_mm=(1.0, 1.0, 1.0))
    assert grid.filled.all()  # the even-odd rule would leave the overlap hollow


def test_inside_out_mesh_still_fills():
    mesh = shapes.cube()
    mesh.invert()
    assert voxelize(mesh, size=8).filled.all()


def test_open_mesh_falls_back_with_a_note():
    mesh = shapes.sphere()
    mesh.update_faces(np.arange(len(mesh.faces)) != 0)  # punch a hole
    grid = voxelize(mesh, size=16)
    assert any("even-odd" in n for n in grid.notes)
    assert grid.filled.sum() > 0.4 * grid.filled.size


def test_vertex_colours_are_sampled(palette):
    mesh = shapes.two_tone_vertex_colours(shapes.sphere())
    grid = voxelize(mesh, size=32, palette=palette)
    top = grid.colour[:, -1, :][grid.filled[:, -1, :]]
    bottom = grid.colour[:, 0, :][grid.filled[:, 0, :]]
    assert set(top.tolist()) == {4}
    assert set(bottom.tolist()) == {1}


def test_texture_colours_survive_a_glb_round_trip(palette, tmp_path):
    path = tmp_path / "cube.glb"
    shapes.two_tone_texture(shapes.cube()).export(path)
    mesh = load_mesh(path)
    assert mesh.visual.kind == "texture"
    grid = voxelize(mesh, size=16, palette=palette)
    assert set(grid.colour[:, 0, :].ravel().tolist()) == {1}
    assert set(grid.colour[:, -1, :].ravel().tolist()) == {14}


def test_mesh_without_colour_uses_the_default(palette):
    grid = voxelize(shapes.cube(), size=8, palette=palette, default_colour=71)
    assert set(grid.colour.ravel().tolist()) == {71}
    assert any("no colour" in n for n in grid.notes)
    with pytest.raises(ValueError):
        voxelize(shapes.cube(), size=8, palette=palette, default_colour=999)


def test_z_up_input_is_turned_upright(tmp_path):
    tall = trimesh.creation.box(extents=(1.0, 1.0, 4.0))  # tall along Z
    path = tmp_path / "tall.stl"
    tall.export(path)
    upright = load_mesh(path, up="z")
    assert upright.extents[1] == pytest.approx(4.0)
    assert load_mesh(path, up="y").extents[1] == pytest.approx(1.0)


def test_unsupported_format(tmp_path):
    with pytest.raises(ValueError):
        load_mesh(tmp_path / "model.fbx")


def test_save_and_load_round_trip(tmp_path, palette):
    grid = voxelize(shapes.two_tone_vertex_colours(shapes.sphere()), size=12, palette=palette)
    path = tmp_path / "voxels.npz"
    grid.save(path)
    loaded = VoxelGrid.load(path)
    np.testing.assert_array_equal(loaded.colour, grid.colour)
    assert loaded.cell_mm == grid.cell_mm
    assert loaded.origin_mm == pytest.approx(grid.origin_mm)
    assert loaded.scale == pytest.approx(grid.scale)
    assert loaded.notes == grid.notes
    assert (loaded.colour[~loaded.filled] == EMPTY).all()
