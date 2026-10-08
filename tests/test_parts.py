import re

import numpy as np
import pytest

from brickbuild.ldraw import LDU_PER_PLATE, LDU_PER_STUD, STUD_PRIMITIVES
from brickbuild.parts import STARTER_BRICKS, get_part


@pytest.mark.parametrize("part", STARTER_BRICKS, ids=lambda p: p.id)
def test_catalogue_matches_library_geometry(library, part):
    """Footprint, height and origin of each part, re-derived from its .dat file."""
    name = f"{part.id}.dat"
    lo, hi = library.bounds(name)
    blo, bhi = library.bounds(name, STUD_PRIMITIVES)

    half_x, half_z = part.sx * LDU_PER_STUD / 2, part.sz * LDU_PER_STUD / 2
    np.testing.assert_array_equal(blo, [-half_x, 0, -half_z])
    np.testing.assert_array_equal(bhi, [half_x, part.h * LDU_PER_PLATE, half_z])
    # Studs stay inside the footprint and only rise above the body.
    assert lo[1] < blo[1]
    np.testing.assert_array_equal(lo[[0, 2]], blo[[0, 2]])
    np.testing.assert_array_equal(hi, bhi)

    bottom_centre = ((blo[0] + bhi[0]) / 2, bhi[1], (blo[2] + bhi[2]) / 2)
    assert bottom_centre == part.bottom_centre


@pytest.mark.parametrize("part", STARTER_BRICKS, ids=lambda p: p.id)
def test_catalogue_names_match_library_titles(library, part):
    title = " ".join(library.title(f"{part.id}.dat").split())
    assert title == part.name
    assert re.fullmatch(r"Brick \d+ x \d+", title)


def test_footprint_rotation():
    brick = get_part("3001")
    assert brick.footprint(0) == (4, 2)
    assert brick.footprint(90) == (2, 4)
    with pytest.raises(ValueError):
        brick.footprint(45)


def test_unknown_part():
    with pytest.raises(KeyError):
        get_part("9999")
