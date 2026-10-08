"""Stage 2: solid voxelisation at brick resolution, with colour sampling.

Cells are one stud wide and deep (8 mm) and one brick tall (9.6 mm). A cell is
solid when its centre lies inside the mesh. Inside-ness comes from vertical
rays cast through every column centre (numpy only, no ray library needed):

* Triangles are projected onto the ground plane. Points on an edge shared by
  two triangles are given to exactly one of them (a top-left rule evaluated
  with identical arithmetic on both sides), so rays through edges and
  vertices are counted once.
* For watertight, consistently wound meshes the signed winding number is
  used, so overlapping closed shells merge into their union. Other meshes
  fall back to the even-odd rule, with a note in the result.

Grid axes are (x, up, z) in the mesh's right handed, Y up frame. The model is
centred horizontally in the grid and stands on layer 0.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import trimesh
from scipy.spatial import cKDTree

from brickbuild.colours import Palette, linear_to_srgb, srgb_to_linear

STUD_MM = 8.0
BRICK_MM = 9.6
CELL_MM = (STUD_MM, BRICK_MM, STUD_MM)
EMPTY = -1
_FORMAT_VERSION = 1


@dataclass
class VoxelGrid:
    colour: np.ndarray  # int32 (nx, ny, nz): LDraw colour code per cell, EMPTY if not solid
    cell_mm: tuple[float, float, float] = CELL_MM
    origin_mm: tuple[float, float, float] = (0.0, 0.0, 0.0)  # min corner of cell (0, 0, 0)
    scale: float = 1.0  # millimetres per unit of the input mesh
    notes: list[str] = field(default_factory=list)

    @property
    def filled(self) -> np.ndarray:
        return self.colour != EMPTY

    @property
    def shape(self) -> tuple[int, int, int]:
        return self.colour.shape

    def save(self, path: Path | str) -> None:
        np.savez_compressed(
            path,
            version=_FORMAT_VERSION,
            colour=self.colour.astype(np.int32),
            cell_mm=np.array(self.cell_mm),
            origin_mm=np.array(self.origin_mm),
            scale=self.scale,
            notes=json.dumps(self.notes),
        )

    @classmethod
    def load(cls, path: Path | str) -> VoxelGrid:
        with np.load(path) as data:
            if int(data["version"]) != _FORMAT_VERSION:
                raise ValueError(f"{path}: unsupported voxel file version {int(data['version'])}")
            return cls(
                colour=data["colour"].astype(np.int32),
                cell_mm=tuple(float(v) for v in data["cell_mm"]),
                origin_mm=tuple(float(v) for v in data["origin_mm"]),
                scale=float(data["scale"]),
                notes=json.loads(str(data["notes"])),
            )


def voxelize(
    mesh: trimesh.Trimesh,
    size: int = 32,
    palette: Palette | None = None,
    default_colour: int = 71,
    cell_mm: tuple[float, float, float] = CELL_MM,
    seed: int = 0,
) -> VoxelGrid:
    """Scale `mesh` so its longest side is `size` studs and fill it with coloured cells.

    Colours come from the mesh texture, vertex or face colours, snapped to
    `palette`. Meshes without colour (and runs without a palette) use
    `default_colour` for every cell.
    """
    if size < 1:
        raise ValueError("size must be at least 1 stud")
    notes: list[str] = []
    extent = mesh.extents
    if not np.all(np.isfinite(extent)) or extent.max() <= 0:
        raise ValueError("mesh has no extent")
    scale = size * STUD_MM / float(extent.max())
    scaled = mesh.copy()
    scaled.apply_scale(scale)

    cell = np.asarray(cell_mm, dtype=float)
    lo, hi = scaled.bounds
    span = hi - lo
    cells = np.round(span / cell, 6)
    shape = np.ceil(cells)  # horizontally: enough columns, centred on the model
    shape[1] = np.floor(cells[1] + 0.5)  # vertically: only layers whose centre can be inside
    shape = np.maximum(shape, 1).astype(int)
    origin = lo - (shape * cell - span) / 2
    origin[1] = lo[1]  # stand on the ground

    tris = (scaled.triangles - origin) / cell
    if scaled.is_watertight and scaled.is_winding_consistent:
        solid = _solid_cells(tris, tuple(shape), winding_sign=1 if scaled.volume >= 0 else -1)
    else:
        notes.append(
            "mesh is not watertight or not consistently wound: used the even-odd fill rule, "
            "so holes in the mesh can leave gaps or stray columns"
        )
        solid = _solid_cells(tris, tuple(shape), winding_sign=None)

    colour = np.full(solid.shape, EMPTY, dtype=np.int32)
    if palette is not None and default_colour not in palette:
        raise ValueError(f"default colour {default_colour} is not in the palette")
    samples = _surface_colours(scaled, solid.sum(), seed) if palette is not None else None
    if samples is None:
        if palette is not None:
            notes.append(f"mesh has no colour information: used colour {default_colour}")
        colour[solid] = default_colour
    else:
        points, rgb = samples
        centres = origin + (np.argwhere(solid) + 0.5) * cell
        colour[solid] = _vote_colours(points, palette.nearest(rgb), centres)

    return VoxelGrid(
        colour=colour,
        cell_mm=tuple(float(c) for c in cell),
        origin_mm=tuple(float(o) for o in origin),
        scale=scale,
        notes=notes,
    )


# Solid fill by vertical ray casting -------------------------------------


def _solid_cells(
    tris: np.ndarray, shape: tuple[int, int, int], winding_sign: int | None
) -> np.ndarray:
    """Cells whose centre is inside the triangles `tris` (F, 3, 3), given in cell units.

    `winding_sign` +1 or -1 uses the signed winding number (sign fixes inside
    out meshes); None uses the even-odd rule.
    """
    nx, ny, nz = shape
    i, k, v, contribution = _column_hits(tris, nx, nz)
    j = np.clip(np.ceil(v - 0.5), 0, ny).astype(np.int64)  # first cell centre above the hit
    delta = np.zeros((nx, ny + 1, nz), dtype=np.int32)
    if winding_sign is None:
        np.add.at(delta, (i, j, k), 1)
        return (np.cumsum(delta, axis=1)[:, :ny, :] % 2) == 1
    np.add.at(delta, (i, j, k), contribution * winding_sign)
    return np.cumsum(delta, axis=1)[:, :ny, :] > 0


def _column_hits(tris: np.ndarray, nx: int, nz: int, max_pairs: int = 2_000_000):
    """Where vertical rays through column centres (i + .5, k + .5) cross triangles.

    Returns column indices i and k, crossing height v (cell units) and the
    winding contribution: +1 where the surface faces down (entering the solid
    while moving up), -1 where it faces up.
    """
    a, b, c = tris[:, 0], tris[:, 1], tris[:, 2]
    # Twice the signed area in the (x, z) plane. Positive means the face normal points down.
    area = (b[:, 0] - a[:, 0]) * (c[:, 2] - a[:, 2]) - (b[:, 2] - a[:, 2]) * (c[:, 0] - a[:, 0])
    keep = area != 0  # faces seen edge on from above add no crossings
    a, b, c, area = a[keep], b[keep], c[keep], area[keep]
    contribution = np.where(area > 0, 1, -1).astype(np.int32)
    flip = area < 0  # make every triangle counter clockwise in the (x, z) plane
    b, c = np.where(flip[:, None], c, b), np.where(flip[:, None], b, c)

    xs = np.stack([a[:, 0], b[:, 0], c[:, 0]], axis=1)
    zs = np.stack([a[:, 2], b[:, 2], c[:, 2]], axis=1)
    i0 = np.maximum(np.ceil(xs.min(axis=1) - 0.5), 0).astype(np.int64)
    i1 = np.minimum(np.floor(xs.max(axis=1) - 0.5), nx - 1).astype(np.int64)
    k0 = np.maximum(np.ceil(zs.min(axis=1) - 0.5), 0).astype(np.int64)
    k1 = np.minimum(np.floor(zs.max(axis=1) - 0.5), nz - 1).astype(np.int64)
    ni = np.maximum(i1 - i0 + 1, 0)
    nk = np.maximum(k1 - k0 + 1, 0)
    count = ni * nk

    out_i, out_k, out_v, out_s = [], [], [], []
    start = 0
    cum = np.cumsum(count)
    while start < len(count):
        # Take a chunk of triangles whose candidate (triangle, column) pairs fit in memory.
        base = cum[start - 1] if start else 0
        stop = max(int(np.searchsorted(cum, base + max_pairs, side="right")), start + 1)
        sl = slice(start, stop)
        cnt = count[sl]
        tri = np.repeat(np.arange(start, stop), cnt)
        if len(tri):
            first = np.repeat(np.cumsum(cnt) - cnt, cnt)
            offset = np.arange(len(tri)) - first
            ii = i0[tri] + offset // nk[tri]
            kk = k0[tri] + offset % nk[tri]
            pu, pw = ii + 0.5, kk + 0.5
            ta, tb, tc = a[tri], b[tri], c[tri]
            e_a = _edge(tb, tc, pu, pw)  # weight of vertex a
            e_b = _edge(tc, ta, pu, pw)
            e_c = _edge(ta, tb, pu, pw)
            hit = _covers(e_a, tb, tc) & _covers(e_b, tc, ta) & _covers(e_c, ta, tb)
            total = e_a + e_b + e_c
            v = (e_a * ta[:, 1] + e_b * tb[:, 1] + e_c * tc[:, 1])[hit] / total[hit]
            out_i.append(ii[hit])
            out_k.append(kk[hit])
            out_v.append(v)
            out_s.append(contribution[tri][hit])
        start = stop
    if not out_i:
        empty = np.zeros(0, dtype=np.int64)
        return empty, empty, np.zeros(0), np.zeros(0, dtype=np.int32)
    return (
        np.concatenate(out_i),
        np.concatenate(out_k),
        np.concatenate(out_v),
        np.concatenate(out_s),
    )


def _edge(p: np.ndarray, q: np.ndarray, xu: np.ndarray, xw: np.ndarray) -> np.ndarray:
    """Edge function of the directed edge p -> q at points (xu, xw), in the (x, z) plane.

    Positive to the left of the edge. It is always evaluated from the
    lexicographically smaller end point, so the two triangles sharing an edge
    get exactly opposite values and agree on which side a point is.
    """
    swap = (q[:, 0] < p[:, 0]) | ((q[:, 0] == p[:, 0]) & (q[:, 2] < p[:, 2]))
    lo = np.where(swap[:, None], q, p)
    hi = np.where(swap[:, None], p, q)
    e = (hi[:, 0] - lo[:, 0]) * (xw - lo[:, 2]) - (hi[:, 2] - lo[:, 2]) * (xu - lo[:, 0])
    return np.where(swap, -e, e)


def _covers(e: np.ndarray, p: np.ndarray, q: np.ndarray) -> np.ndarray:
    """Inside test for one edge, with a tie rule that gives edge points to one side only."""
    du = q[:, 0] - p[:, 0]
    dw = q[:, 2] - p[:, 2]
    owns_boundary = (dw < 0) | ((dw == 0) & (du > 0))
    return (e > 0) | ((e == 0) & owns_boundary)


# Colour sampling ---------------------------------------------------------


def _surface_colours(mesh: trimesh.Trimesh, n_cells: int, seed: int):
    """Random surface points with their sRGB colour, or None if the mesh has no colour."""
    visual = mesh.visual
    kind = visual.kind
    if kind is None:
        return None
    cell_area = STUD_MM * STUD_MM
    count = int(np.clip(mesh.area / cell_area * 24, 20_000, 500_000))
    count = max(count, min(4 * n_cells, 500_000))
    points, face, bary = trimesh.sample.sample_surface(
        mesh, count, return_barycentric=True, seed=seed
    )
    corners = mesh.faces[face]
    if kind == "vertex":
        vc = np.asarray(visual.vertex_colors, dtype=float)[:, :3]
        rgb = np.einsum("nk,nkc->nc", bary, vc[corners])
    elif kind == "face":
        rgb = np.asarray(visual.face_colors, dtype=float)[face, :3]
    elif kind == "texture":
        rgb = _texture_colours(visual, corners, bary)
    else:
        return None
    return points, rgb


def _texture_colours(visual, corners: np.ndarray, bary: np.ndarray) -> np.ndarray:
    material = visual.material
    if isinstance(material, trimesh.visual.material.SimpleMaterial):
        image, factor = material.image, None
        flat = np.asarray(material.diffuse, dtype=float)[:3]
    else:
        # glTF style: texture times baseColorFactor, the factor being linear.
        image = getattr(material, "baseColorTexture", None)
        factor = getattr(material, "baseColorFactor", None)
        flat = np.asarray(material.main_color, dtype=float)[:3]
    uv = getattr(visual, "uv", None)
    if image is None or uv is None:
        return np.tile(flat, (len(corners), 1))
    uv_points = np.einsum("nk,nkc->nc", bary, np.asarray(uv)[corners])
    rgb = trimesh.visual.color.uv_to_interpolated_color(uv_points, image)[:, :3].astype(float)
    if factor is not None:
        f = np.asarray(factor, dtype=float)[:3] / 255.0
        rgb = linear_to_srgb(srgb_to_linear(rgb) * f)
    return rgb


def _vote_colours(points: np.ndarray, codes: np.ndarray, centres: np.ndarray, k: int = 8):
    """Majority colour among the k surface samples nearest to each cell centre.

    Voting over already snapped colours avoids inventing blends at colour
    borders. Ties go to the nearer sample.
    """
    k = min(k, len(points))
    _, idx = cKDTree(points).query(centres, k=k)
    idx = idx.reshape(len(centres), k)
    near = codes[idx]
    votes = (near[:, :, None] == near[:, None, :]).sum(axis=2).astype(float)
    votes -= np.arange(k) * 1e-3
    return near[np.arange(len(near)), votes.argmax(axis=1)]
