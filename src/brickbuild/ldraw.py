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

from brickbuild.env import LIBRARY_ENV

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
