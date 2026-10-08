"""LDraw library access, plus reading and writing LDraw models.

Conversion between the internal stud grid and LDraw coordinates happens only
in this module. LDraw facts used here (LDraw File Format 1.0.2 spec):

* right handed coordinates, -Y is up
* line type 1: `1 <colour> x y z a b c d e f g h i <file>` with
  u' = a*u + b*v + c*w + x, v' = d*u + e*v + f*w + y, w' = g*u + h*v + i*w + z
* sub files are searched in PARTS, P, MODELS and the referencing file's folder
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np

from brickbuild.brick import Brick
from brickbuild.env import LIBRARY_ENV
from brickbuild.parts import get_part

LDU_MM = 0.4
LDU_PER_STUD = 20
LDU_PER_PLATE = 8

_SEARCH_DIRS = ("parts", "p", "models")


class LibraryError(RuntimeError):
    """The LDraw library is missing, incomplete or lacks a referenced file."""


class LDrawLibrary:
    """Read access to an unpacked LDraw parts library."""

    def __init__(self, root: Path | str):
        root = Path(root).expanduser().resolve()
        missing = [n for n in ("parts", "p") if not (root / n).is_dir()]
        if not (root / "LDConfig.ldr").is_file():
            missing.append("LDConfig.ldr")
        if missing:
            raise LibraryError(
                f"{root} is not an LDraw library folder (missing: {', '.join(missing)}). "
                "It must directly contain parts/, p/ and LDConfig.ldr."
            )
        self.root = root
        self._case_index: dict[str, Path] | None = None
        self._points: dict[tuple[str, tuple[str, ...]], np.ndarray] = {}

    @classmethod
    def from_env(cls) -> LDrawLibrary:
        raw = os.environ.get(LIBRARY_ENV)
        if not raw:
            raise LibraryError(
                f"{LIBRARY_ENV} is not set. Point it at the unpacked LDraw library, "
                "for example in a .env file (see .env.example)."
            )
        return cls(raw)

    @property
    def ldconfig_path(self) -> Path:
        return self.root / "LDConfig.ldr"

    def resolve(self, name: str, relative_to: Path | None = None) -> Path:
        """Find a referenced file. Lookup ignores case and accepts either slash."""
        key = name.strip().replace("\\", "/").lower()
        bases = [self.root / d for d in _SEARCH_DIRS]
        if relative_to is not None:
            bases.append(relative_to)
        for base in bases:
            candidate = base / key
            if candidate.is_file():
                return candidate
        # The official library uses lower case names, but other files may not.
        index = self._index()
        for d in _SEARCH_DIRS:
            hit = index.get(f"{d}/{key}")
            if hit is not None:
                return hit
        raise LibraryError(f"cannot find {name!r} in the LDraw library at {self.root}")

    def _index(self) -> dict[str, Path]:
        if self._case_index is None:
            index: dict[str, Path] = {}
            for d in _SEARCH_DIRS:
                base = self.root / d
                for dirpath, _dirs, files in os.walk(base):
                    for f in files:
                        path = Path(dirpath) / f
                        index[path.relative_to(self.root).as_posix().lower()] = path
            self._case_index = index
        return self._case_index

    def title(self, name: str) -> str:
        """The description on the first line of a library file."""
        with open(self.resolve(name), encoding="utf-8", errors="replace") as fh:
            first = fh.readline().strip()
        return first[2:].strip() if first.startswith("0 ") else ""

    def points(self, name: str, exclude: tuple[str, ...] = ()) -> np.ndarray:
        """All geometry vertices of a file in its own coordinates, sub files included.

        Vertices come from line types 2, 3 and 4. Conditional lines (type 5)
        are not geometry and are skipped. Sub files whose base name starts
        with one of the `exclude` prefixes are left out at any depth.
        """
        return self._points_at(self.resolve(name), exclude)

    def _points_at(self, path: Path, exclude: tuple[str, ...]) -> np.ndarray:
        key = (path.as_posix().lower(), exclude)
        cached = self._points.get(key)
        if cached is not None:
            return cached
        chunks: list[np.ndarray] = []
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                tok = line.split()
                if not tok:
                    continue
                kind = tok[0]
                if kind == "1" and len(tok) >= 15:
                    sub = " ".join(tok[14:])
                    base = sub.replace("\\", "/").rsplit("/", 1)[-1].lower()
                    if any(base.startswith(p) for p in exclude):
                        continue
                    vals = np.array(tok[2:14], dtype=float)
                    offset, matrix = vals[:3], vals[3:].reshape(3, 3)
                    sub_pts = self._points_at(self.resolve(sub, path.parent), exclude)
                    if len(sub_pts):
                        chunks.append(sub_pts @ matrix.T + offset)
                elif kind in ("2", "3", "4"):
                    n = int(kind)
                    chunks.append(np.array(tok[2 : 2 + 3 * n], dtype=float).reshape(n, 3))
        pts = np.unique(np.vstack(chunks), axis=0) if chunks else np.zeros((0, 3))
        self._points[key] = pts
        return pts

    def bounds(self, name: str, exclude: tuple[str, ...] = ()) -> tuple[np.ndarray, np.ndarray]:
        """Axis aligned bounding box (min, max) of a file in its own LDU coordinates."""
        pts = self.points(name, exclude)
        if not len(pts):
            raise LibraryError(f"{name} has no geometry")
        return pts.min(axis=0), pts.max(axis=0)


# Stud primitives (stud*.dat, stug*.dat). Leaving them out gives the brick body.
STUD_PRIMITIVES = ("stud", "stug")


# Model writing and reading ----------------------------------------------
#
# Grid frame: x, up (in plates), z; right handed, the frame of the Y up input
# mesh. LDraw frame: X = x, Y = -up, Z = -z. That is a rotation of 180 degrees
# about X, which puts -Y up without mirroring the model.

GRID_TO_LDRAW = np.diag([LDU_PER_STUD, -LDU_PER_PLATE, -LDU_PER_STUD]).astype(float)

# Part rotations about the vertical axis. At 90 degrees the part's local X
# axis runs along grid z, so its footprint (sx, sz) becomes (w, d) = (sz, sx).
ROTATIONS = {
    0: np.eye(3),
    90: np.array([[0.0, 0.0, 1.0], [0.0, 1.0, 0.0], [-1.0, 0.0, 0.0]]),
}
# Accepted when reading: 180 and 270 degrees give the same footprints as 0 and 90.
_READ_ROTATIONS = (
    (0, ROTATIONS[0]),
    (90, ROTATIONS[90]),
    (0, np.diag([-1.0, 1.0, -1.0])),
    (90, np.array([[0.0, 0.0, -1.0], [0.0, 1.0, 0.0], [1.0, 0.0, 0.0]])),
)


def grid_to_ldraw(point) -> np.ndarray:
    """(x studs, up plates, z studs) to LDraw (X, Y, Z) in LDU."""
    return GRID_TO_LDRAW @ np.asarray(point, dtype=float)


def ldraw_to_grid(point) -> np.ndarray:
    return np.linalg.solve(GRID_TO_LDRAW, np.asarray(point, dtype=float))


def placement(brick: Brick) -> tuple[np.ndarray, np.ndarray]:
    """LDraw position and rotation matrix that put `brick`'s part on its grid spot."""
    part = get_part(brick.part)
    rotation = ROTATIONS[brick.rot]
    bottom_centre = grid_to_ldraw((brick.x + brick.w / 2, brick.y, brick.z + brick.d / 2))
    return bottom_centre - rotation @ np.asarray(part.bottom_centre, dtype=float), rotation


def part_line(brick: Brick) -> str:
    position, rotation = placement(brick)
    numbers = [*position, *rotation.ravel()]
    return f"1 {brick.colour} {' '.join(_num(v) for v in numbers)} {brick.part}.dat"


def write_model(bricks: list[Brick], path: Path | str, title: str) -> None:
    """Write an .ldr file, bottom layer first, with one STEP per layer."""
    path = Path(path)
    lines = [
        f"0 {title}",
        f"0 Name: {path.name}",
        "0 Author: brickbuild",
        "",
    ]
    by_layer: dict[int, list[Brick]] = {}
    for brick in bricks:
        by_layer.setdefault(brick.y, []).append(brick)
    for y in sorted(by_layer):
        lines += [part_line(b) for b in sorted(by_layer[y], key=lambda b: (b.z, b.x))]
        lines.append("0 STEP")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def read_model(path: Path | str) -> list[Brick]:
    """Read back the part lines of an .ldr file written by `write_model`.

    Only catalogue parts placed upright on the stud grid are accepted.
    """
    bricks = []
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        tok = line.split()
        if not tok or tok[0] != "1":
            continue
        where = f"{path}:{number}"
        if len(tok) < 15:
            raise ValueError(f"{where}: malformed part line")
        part_id = " ".join(tok[14:]).lower().removesuffix(".dat")
        try:
            part = get_part(part_id)
        except KeyError as exc:
            raise ValueError(f"{where}: {exc.args[0]}") from None
        vals = np.array(tok[2:14], dtype=float)
        position, matrix = vals[:3], vals[3:].reshape(3, 3)
        rot = next((r for r, m in _READ_ROTATIONS if np.allclose(matrix, m)), None)
        if rot is None:
            raise ValueError(f"{where}: part is not upright with a 90 degree step rotation")
        w, d = part.footprint(rot)
        centre = ldraw_to_grid(position + matrix @ np.asarray(part.bottom_centre, dtype=float))
        corner = centre - (w / 2, 0, d / 2)
        rounded = np.round(corner)
        if not np.allclose(corner, rounded, atol=1e-6):
            raise ValueError(f"{where}: part is not on the stud grid")
        x, y, z = (int(v) for v in rounded)
        bricks.append(Brick(part.id, x, y, z, w, d, part.h, rot, int(tok[1])))
    return bricks


def _num(value: float) -> str:
    rounded = round(value)
    if abs(value - rounded) < 1e-9:
        return str(int(rounded)) if rounded != 0 else "0"
    return f"{value:.6g}"
