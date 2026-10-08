"""Part catalogue: LDraw part ids, footprints and heights.

Footprints and origins were confirmed by reading each part's .dat file in the
LDraw library (2026-10 complete.zip). For every starter brick the origin is
the centre of the top face of the body (studs excluded): the body spans
y = 0..24 LDU with the bottom at +24, the studs rise to y = -4, the footprint
is centred on x = z = 0 and the long side runs along the local X axis.
tests/test_parts.py re-derives all of this from the library.
"""

from __future__ import annotations

from dataclasses import dataclass

PLATES_PER_BRICK = 3


@dataclass(frozen=True)
class Part:
    id: str  # LDraw part id, e.g. "3001"
    name: str
    sx: int  # footprint along the part's local X axis, in studs
    sz: int  # footprint along the part's local Z axis, in studs
    h: int  # height in plate units
    # Centre of the bottom face of the body, in the part's own LDU coordinates.
    bottom_centre: tuple[int, int, int]

    @property
    def area(self) -> int:
        return self.sx * self.sz

    def footprint(self, rot: int) -> tuple[int, int]:
        """(w, d) on the stud grid after `rot` degrees about the vertical axis."""
        if rot == 0:
            return self.sx, self.sz
        if rot == 90:
            return self.sz, self.sx
        raise ValueError(f"rotation must be 0 or 90, got {rot}")


def _brick(part_id: str, sz: int, sx: int) -> Part:
    return Part(
        id=part_id,
        name=f"Brick {sz} x {sx}",
        sx=sx,
        sz=sz,
        h=PLATES_PER_BRICK,
        bottom_centre=(0, 24, 0),
    )


STARTER_BRICKS: tuple[Part, ...] = (
    _brick("3005", 1, 1),
    _brick("3004", 1, 2),
    _brick("3622", 1, 3),
    _brick("3010", 1, 4),
    _brick("3009", 1, 6),
    _brick("3008", 1, 8),
    _brick("3003", 2, 2),
    _brick("3002", 2, 3),
    _brick("3001", 2, 4),
    _brick("2456", 2, 6),
    _brick("3007", 2, 8),
)

PARTS: dict[str, Part] = {p.id: p for p in STARTER_BRICKS}


def get_part(part_id: str) -> Part:
    try:
        return PARTS[part_id]
    except KeyError:
        raise KeyError(f"part {part_id!r} is not in the brickbuild catalogue") from None
