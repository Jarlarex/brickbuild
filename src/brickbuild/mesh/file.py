"""File mesh provider: load a mesh from disk and bring it into the Y up frame."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import trimesh

SUPPORTED_SUFFIXES = (".glb", ".gltf", ".obj", ".stl")

# Z up to Y up, as a proper rotation (-90 degrees about X) so the model is
# never mirrored: (x, y, z) -> (x, z, -y).
_Z_UP_TO_Y_UP = np.array(
    [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [0.0, -1.0, 0.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]
)


def load_mesh(path: Path | str, up: str = "y") -> trimesh.Trimesh:
    """Load a mesh file as a single triangle mesh with +Y up.

    `up` names the input's vertical axis: "y" (glTF convention) or "z"
    (common for STL and CAD exports). Scenes are flattened into one mesh.
    """
    path = Path(path)
    if path.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise ValueError(
            f"unsupported mesh format {path.suffix!r}; use one of {', '.join(SUPPORTED_SUFFIXES)}"
        )
    if up not in ("y", "z"):
        raise ValueError(f"up axis must be 'y' or 'z', got {up!r}")
    mesh = trimesh.load(path, force="mesh")
    if not isinstance(mesh, trimesh.Trimesh) or len(mesh.faces) == 0:
        raise ValueError(f"{path} contains no triangles")
    if up == "z":
        mesh.apply_transform(_Z_UP_TO_Y_UP)
    return mesh
