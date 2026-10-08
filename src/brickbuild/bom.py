"""Parts list. Phase 1 has the counts; CSV and BrickLink exports come in phase 3."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from brickbuild.brick import Brick


@dataclass(frozen=True)
class PartsSummary:
    total: int
    by_part: dict[str, int]  # part id -> count
    by_lot: dict[tuple[str, int], int]  # (part id, colour) -> count

    @property
    def distinct_parts(self) -> int:
        return len(self.by_part)

    @property
    def distinct_lots(self) -> int:
        """Distinct part and colour combinations, as you would order them."""
        return len(self.by_lot)


def summarise(bricks: list[Brick]) -> PartsSummary:
    by_part = Counter(b.part for b in bricks)
    by_lot = Counter((b.part, b.colour) for b in bricks)
    return PartsSummary(
        total=len(bricks),
        by_part=dict(by_part.most_common()),
        by_lot=dict(by_lot.most_common()),
    )
