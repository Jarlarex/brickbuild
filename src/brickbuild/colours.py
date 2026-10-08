"""Colour palette loading (from LDConfig.ldr) and nearest colour matching in CIELAB.

The palette is read from the LDraw library's LDConfig.ldr; no colour values
are hardcoded here. LDConfig groups colours under section comments such as
`0 // LDraw Solid Colours`. Only plain opaque colours from the solid section
are used for matching: transparent, chrome, metallic, pearl, rubber, glitter,
speckle, glow and the internal codes 16 and 24 are left out.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import ArrayLike

SOLID_SECTION = "Solid Colours"
_MATERIAL_WORDS = ("CHROME", "PEARLESCENT", "RUBBER", "MATTE_METALLIC", "METAL", "MATERIAL")
_SECTION = re.compile(r"^0\s+//\s+LDraw\s+(.+?Colours)\s*$")


@dataclass(frozen=True)
class LDrawColour:
    code: int
    name: str
    rgb: tuple[int, int, int]
    alpha: int  # 255 is opaque
    luminance: int  # non zero for glow in the dark colours
    material: str | None  # CHROME, METAL, ... or None for plain plastic
    section: str  # LDConfig section, e.g. "Solid Colours"

    @property
    def is_plain_solid(self) -> bool:
        return (
            self.section == SOLID_SECTION
            and self.alpha == 255
            and self.luminance == 0
            and self.material is None
        )


def parse_ldconfig(text: str) -> list[LDrawColour]:
    colours = []
    section = ""
    for raw in text.splitlines():
        line = raw.strip()
        m = _SECTION.match(line)
        if m:
            section = m.group(1)
            continue
        tok = line.split()
        if len(tok) < 3 or tok[0] != "0" or tok[1] != "!COLOUR":
            continue
        fields = {}
        material = None
        i = 3
        while i < len(tok):
            word = tok[i]
            if word in ("CODE", "VALUE", "EDGE", "ALPHA", "LUMINANCE") and i + 1 < len(tok):
                fields[word] = tok[i + 1]
                i += 2
            elif word in _MATERIAL_WORDS:
                material = word if word != "MATERIAL" else f"MATERIAL {tok[i + 1]}"
                break  # material parameters follow, nothing else we need
            else:
                i += 1
        value = fields["VALUE"].lstrip("#")
        colours.append(
            LDrawColour(
                code=int(fields["CODE"]),
                name=tok[2],
                rgb=(int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)),
                alpha=int(fields.get("ALPHA", 255)),
                luminance=int(fields.get("LUMINANCE", 0)),
                material=material,
                section=section,
            )
        )
    return colours


def load_ldconfig(path: Path) -> list[LDrawColour]:
    return parse_ldconfig(Path(path).read_text(encoding="utf-8", errors="replace"))


# sRGB (D65) to CIELAB. Standard IEC 61966-2-1 and CIE 1976 formulas.
_SRGB_TO_XYZ = np.array(
    [
        [0.4124564, 0.3575761, 0.1804375],
        [0.2126729, 0.7151522, 0.0721750],
        [0.0193339, 0.1191920, 0.9503041],
    ]
)
_D65_WHITE = np.array([0.95047, 1.0, 1.08883])


def srgb_to_linear(rgb: ArrayLike) -> np.ndarray:
    """8 bit sRGB values (0..255) to linear RGB (0..1)."""
    c = np.asarray(rgb, dtype=float) / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(linear: ArrayLike) -> np.ndarray:
    """Linear RGB (0..1) to 8 bit sRGB values (0..255, float)."""
    c = np.clip(np.asarray(linear, dtype=float), 0.0, 1.0)
    return 255.0 * np.where(c <= 0.0031308, c * 12.92, 1.055 * c ** (1 / 2.4) - 0.055)


def srgb_to_lab(rgb: ArrayLike) -> np.ndarray:
    """8 bit sRGB values, shape (..., 3), to CIELAB (L*, a*, b*)."""
    xyz = srgb_to_linear(rgb) @ _SRGB_TO_XYZ.T / _D65_WHITE
    eps, kappa = 216 / 24389, 24389 / 27
    f = np.where(xyz > eps, np.cbrt(xyz), (kappa * xyz + 16) / 116)
    lab = np.empty_like(f)
    lab[..., 0] = 116 * f[..., 1] - 16
    lab[..., 1] = 500 * (f[..., 0] - f[..., 1])
    lab[..., 2] = 200 * (f[..., 1] - f[..., 2])
    return lab


class Palette:
    """A set of LDraw colours to snap to, using CIE76 distance in CIELAB."""

    def __init__(self, colours: list[LDrawColour]):
        if not colours:
            raise ValueError("palette is empty")
        self.colours = list(colours)
        self.codes = np.array([c.code for c in colours], dtype=np.int32)
        self.lab = srgb_to_lab(np.array([c.rgb for c in colours]))
        self._by_code = {c.code: c for c in colours}

    @classmethod
    def from_ldconfig(cls, path: Path) -> Palette:
        return cls([c for c in load_ldconfig(path) if c.is_plain_solid])

    def __contains__(self, code: int) -> bool:
        return code in self._by_code

    def __len__(self) -> int:
        return len(self.colours)

    def get(self, code: int) -> LDrawColour:
        return self._by_code[code]

    def nearest(self, rgb: ArrayLike, chunk: int = 8192) -> np.ndarray:
        """LDraw codes of the nearest palette colour for each 8 bit sRGB row."""
        lab = srgb_to_lab(np.asarray(rgb, dtype=float).reshape(-1, 3))
        out = np.empty(len(lab), dtype=np.int32)
        for start in range(0, len(lab), chunk):
            block = lab[start : start + chunk]
            d2 = ((block[:, None, :] - self.lab[None, :, :]) ** 2).sum(axis=2)
            out[start : start + chunk] = self.codes[d2.argmin(axis=1)]
        return out
