"""Greedy merge of same colour cells into bricks, largest part first.

Each layer is tiled on its own. Parts are tried from the largest area down;
on equal area the 2 wide part goes first, being the more common one (2x4
before 1x8, 2x3 before 1x6, 2x2 before 1x4). Within a part, positions are
taken in grid order wherever the whole footprint is free and one colour.
The preferred long axis alternates between layers so seams tend to cross.
This is the phase 1 baseline; phase 2 adds connectivity and optimisation.
"""

from __future__ import annotations

import numpy as np

from brickbuild.brick import Brick
from brickbuild.parts import PLATES_PER_BRICK, STARTER_BRICKS, Part
from brickbuild.voxel import BRICK_MM, EMPTY, VoxelGrid


def merge_order(parts: tuple[Part, ...] = STARTER_BRICKS) -> list[Part]:
    return sorted(parts, key=lambda p: (-p.area, -min(p.sx, p.sz), p.id))


def greedy_layout(grid: VoxelGrid, parts: tuple[Part, ...] = STARTER_BRICKS) -> list[Brick]:
    if not np.isclose(grid.cell_mm[1], BRICK_MM):
        raise ValueError("the greedy layout needs brick height (9.6 mm) layers")
    order = merge_order(parts)
    bricks: list[Brick] = []
    for layer in range(grid.shape[1]):
        bricks += merge_layer(grid.colour[:, layer, :], layer * PLATES_PER_BRICK, order, layer % 2)
    return bricks


def merge_layer(colour: np.ndarray, y: int, order: list[Part], parity: int) -> list[Brick]:
    """Tile one layer, given as an (nx, nz) array of colour codes (EMPTY for none)."""
    nx, nz = colour.shape
    free = colour != EMPTY
    bricks: list[Brick] = []
    for part in order:
        rotations = [0] if part.sx == part.sz else [0, 90]
        if parity:
            rotations.reverse()  # long side along z first on odd layers
        for rot in rotations:
            w, d = part.footprint(rot)
            if w > nx or d > nz:
                continue
            for code in np.unique(colour[free]):
                fits = _windows_all_true(free & (colour == code), w, d)
                for x, z in np.argwhere(fits):
                    if free[x : x + w, z : z + d].all():
                        free[x : x + w, z : z + d] = False
                        bricks.append(
                            Brick(part.id, int(x), y, int(z), w, d, part.h, rot, int(code))
                        )
    if free.any():
        raise RuntimeError(f"layer at y={y}: {int(free.sum())} cells left uncovered")
    return bricks


def _windows_all_true(mask: np.ndarray, w: int, d: int) -> np.ndarray:
    """For each (x, z), whether mask[x:x+w, z:z+d] is all true. Summed area table."""
    table = np.zeros((mask.shape[0] + 1, mask.shape[1] + 1), dtype=np.int32)
    table[1:, 1:] = mask.cumsum(axis=0).cumsum(axis=1)
    sums = table[w:, d:] - table[:-w, d:] - table[w:, :-d] + table[:-w, :-d]
    return sums == w * d
