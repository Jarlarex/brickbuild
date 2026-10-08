"""The internal brick representation shared by every stage after voxelisation."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

from brickbuild.parts import get_part

_FORMAT = "brickbuild.layout"
_FORMAT_VERSION = 1


@dataclass(frozen=True)
class Brick:
    part: str  # LDraw part id, e.g. "3001"
    x: int  # stud grid position of the min corner
    y: int  # height of the bottom in plate units, 0 = ground (a brick is 3 plates)
    z: int
    w: int  # footprint in studs along x, after rotation
    d: int  # footprint in studs along z, after rotation
    h: int  # height in plate units (brick = 3)
    rot: int  # 0 or 90 degrees about the vertical axis
    colour: int  # LDraw colour code

    def validate(self) -> None:
        part = get_part(self.part)
        if (self.w, self.d) != part.footprint(self.rot):
            raise ValueError(f"{self}: footprint does not match part {part.id} at {self.rot}")
        if self.h != part.h:
            raise ValueError(f"{self}: height does not match part {part.id}")

    def cells(self) -> Iterable[tuple[int, int, int]]:
        """Every (x, y, z) unit cell the brick body occupies, y in plates."""
        for dx in range(self.w):
            for dy in range(self.h):
                for dz in range(self.d):
                    yield self.x + dx, self.y + dy, self.z + dz


def find_overlaps(bricks: list[Brick]) -> list[tuple[int, int]]:
    """Index pairs of bricks whose bodies share at least one cell."""
    owner: dict[tuple[int, int, int], int] = {}
    pairs: set[tuple[int, int]] = set()
    for index, brick in enumerate(bricks):
        for cell in brick.cells():
            other = owner.setdefault(cell, index)
            if other != index:
                pairs.add((other, index))
    return sorted(pairs)


def occupancy(bricks: list[Brick]) -> dict[tuple[int, int, int], int]:
    """Number of bricks covering each occupied cell."""
    counts: dict[tuple[int, int, int], int] = defaultdict(int)
    for brick in bricks:
        for cell in brick.cells():
            counts[cell] += 1
    return dict(counts)


def save_layout(bricks: list[Brick], path: Path | str, notes: list[str] | None = None) -> None:
    data = {
        "format": _FORMAT,
        "version": _FORMAT_VERSION,
        "y_unit": "plate",
        "notes": notes or [],
        "bricks": [asdict(b) for b in bricks],
    }
    Path(path).write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")


def load_layout(path: Path | str) -> tuple[list[Brick], list[str]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("format") != _FORMAT or data.get("version") != _FORMAT_VERSION:
        raise ValueError(f"{path} is not a brickbuild layout file (version {_FORMAT_VERSION})")
    bricks = [Brick(**b) for b in data["bricks"]]
    for brick in bricks:
        brick.validate()
    return bricks, list(data.get("notes", []))
