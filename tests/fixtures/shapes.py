"""Procedural test meshes. Nothing binary is committed; tests build these on the fly.

All shapes are Y up, watertight and wound with outward normals.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import trimesh
from PIL import Image

# Fixture colours (test inputs only, not a palette). Equal to the LDConfig.ldr
# values of Red (4), Blue (1) and Yellow (14), so the expected snap is clear.
RED = (180, 0, 0)
BLUE = (30, 90, 168)
YELLOW = (250, 200, 10)


def cube(size: float = 1.0) -> trimesh.Trimesh:
    return trimesh.creation.box(extents=(size, size, size))


def sphere(radius: float = 1.0, subdivisions: int = 5) -> trimesh.Trimesh:
    return trimesh.creation.icosphere(subdivisions=subdivisions, radius=radius)


def arch(outer: float = 16.0, inner: float = 10.0, depth: float = 4.0, segments: int = 48):
    """Half annulus standing on its two legs: a round arch with an opening under it."""
    theta = np.linspace(0.0, np.pi, segments + 1)
    cos, sin = np.cos(theta), np.sin(theta)
    sin[[0, -1]] = 0.0  # both legs exactly on the ground
    h = depth / 2
    verts = []
    for c, s in zip(cos, sin, strict=True):
        verts += [
            (outer * c, outer * s, h),  # outer front
            (outer * c, outer * s, -h),  # outer back
            (inner * c, inner * s, h),  # inner front
            (inner * c, inner * s, -h),  # inner back
        ]
    faces = []
    for i in range(segments):
        of, ob, inf, ib = 4 * i, 4 * i + 1, 4 * i + 2, 4 * i + 3
        of1, ob1, if1, ib1 = of + 4, ob + 4, inf + 4, ib + 4
        faces += [(inf, of, of1), (inf, of1, if1)]  # front, normal +z
        faces += [(ib, ob1, ob), (ib, ib1, ob1)]  # back, normal -z
        faces += [(of, ob, ob1), (of, ob1, of1)]  # outer curve, normal outwards
        faces += [(inf, if1, ib1), (inf, ib1, ib)]  # inner curve, normal towards the centre
    n = 4 * segments
    faces += [(0, 2, 3), (0, 3, 1)]  # right leg, normal -y
    faces += [(n, n + 3, n + 2), (n, n + 1, n + 3)]  # left leg, normal -y
    return trimesh.Trimesh(vertices=np.array(verts), faces=np.array(faces), process=True)


def two_tone_vertex_colours(mesh: trimesh.Trimesh, bottom=BLUE, top=RED) -> trimesh.Trimesh:
    """Colour vertices above the middle height `top` and the rest `bottom`."""
    mid = mesh.bounds.mean(axis=0)[1]
    rgb = np.where(mesh.vertices[:, 1:2] > mid, top, bottom)
    rgba = np.hstack([rgb, np.full((len(rgb), 1), 255)]).astype(np.uint8)
    mesh.visual = trimesh.visual.ColorVisuals(mesh, vertex_colors=rgba)
    return mesh


def two_tone_texture(mesh: trimesh.Trimesh, bottom=BLUE, top=YELLOW) -> trimesh.Trimesh:
    """Texture whose left half is `bottom` and right half `top`; u follows the height.

    The colour changes half way up the mesh.
    """
    image = np.zeros((8, 64, 3), dtype=np.uint8)
    image[:, :32] = bottom
    image[:, 32:] = top
    lo, hi = mesh.bounds[:, 1]
    u = 0.25 + 0.5 * (mesh.vertices[:, 1] - lo) / (hi - lo)
    uv = np.column_stack([u, np.full_like(u, 0.5)])
    # Explicit white base colour factor: trimesh's default would darken the texture.
    material = trimesh.visual.material.PBRMaterial(
        baseColorTexture=Image.fromarray(image), baseColorFactor=[255, 255, 255, 255]
    )
    mesh.visual = trimesh.visual.TextureVisuals(uv=uv, material=material)
    return mesh


def write_fixtures(out_dir: Path) -> dict[str, Path]:
    """Write the acceptance fixtures, one per supported file format."""
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "sphere": out_dir / "sphere.obj",
        "cube": out_dir / "cube.glb",
        "arch": out_dir / "arch.stl",
    }
    two_tone_vertex_colours(sphere()).export(paths["sphere"])
    two_tone_texture(cube()).export(paths["cube"])
    arch().export(paths["arch"])
    return paths
