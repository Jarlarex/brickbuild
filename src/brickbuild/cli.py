"""Command line interface. One subcommand per pipeline stage, plus `build` for all of them.

Every stage reads and writes a plain file in the output folder, named after
the input: <name>.mesh.glb, <name>.voxels.npz, <name>.layout.json, <name>.ldr.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import trimesh
import typer

from brickbuild import __version__
from brickbuild.bom import summarise
from brickbuild.brick import Brick, load_layout, save_layout
from brickbuild.colours import Palette
from brickbuild.env import LIBRARY_ENV, load_env
from brickbuild.layout import greedy_layout
from brickbuild.ldraw import LDU_MM, STUD_PRIMITIVES, LDrawLibrary, LibraryError, write_model
from brickbuild.mesh import load_mesh
from brickbuild.parts import get_part
from brickbuild.voxel import STUD_MM, VoxelGrid, voxelize

PLATE_MM = 3.2

app = typer.Typer(
    help="Turn a 3D mesh into a buildable brick model (LDraw compatible parts).",
    no_args_is_help=True,
    add_completion=False,
)

_STAGE_SUFFIXES = (".mesh", ".voxels", ".layout")

MeshArg = typer.Argument(..., exists=True, dir_okay=False, help="Mesh file (.glb .gltf .obj .stl)")
VoxelsArg = typer.Argument(..., exists=True, dir_okay=False, help="<name>.voxels.npz")
LayoutArg = typer.Argument(..., exists=True, dir_okay=False, help="<name>.layout.json")
OutOpt = typer.Option(Path("out"), "--out", "-o", help="Output folder.")
SizeOpt = typer.Option(32, "--size", min=1, help="Longest side of the model, in studs.")
UpOpt = typer.Option("y", "--up", help="Vertical axis of the input mesh: y or z.")
ColourOpt = typer.Option(
    71, "--default-colour", help="LDraw colour code for meshes without colour."
)


def _version(value: bool) -> None:
    if value:
        typer.echo(f"brickbuild {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False, "--version", callback=_version, is_eager=True, help="Show the version and exit."
    ),
) -> None:
    load_env()


def _fail(message: str) -> typer.Exit:
    typer.secho(f"error: {message}", fg=typer.colors.RED, err=True)
    return typer.Exit(1)


def _open_library() -> LDrawLibrary:
    try:
        return LDrawLibrary.from_env()
    except LibraryError as exc:
        raise _fail(str(exc)) from exc


def _palette() -> Palette:
    return Palette.from_ldconfig(_open_library().ldconfig_path)


def _name(path: Path) -> str:
    """Model name from an input or stage file: 'out/sphere.voxels.npz' -> 'sphere'."""
    stem = Path(path.stem)
    while stem.suffix in _STAGE_SUFFIXES:
        stem = Path(stem.stem)
    return str(stem)


def _fmt(v) -> str:
    return "(" + ", ".join(f"{x:g}" for x in v) + ")"


def _load(path: Path, up: str) -> trimesh.Trimesh:
    try:
        return load_mesh(path, up=up)
    except ValueError as exc:
        raise _fail(str(exc)) from exc


def _voxelize(mesh, size: int, palette: Palette, default_colour: int) -> VoxelGrid:
    try:
        return voxelize(mesh, size=size, palette=palette, default_colour=default_colour)
    except ValueError as exc:
        raise _fail(str(exc)) from exc


def _report(bricks: list[Brick], palette: Palette | None, notes: list[str]) -> None:
    """Parts and size summary. Printed after every stage that produces bricks."""
    summary = summarise(bricks)
    typer.echo(
        f"parts: {summary.total} total, {summary.distinct_parts} distinct parts, "
        f"{summary.distinct_lots} distinct part and colour combinations"
    )
    for part_id, count in summary.by_part.items():
        typer.echo(f"  {count:6d} x {part_id:<5} {get_part(part_id).name}")
    colours: dict[int, int] = {}
    for brick in bricks:
        colours[brick.colour] = colours.get(brick.colour, 0) + 1
    names = []
    for code, count in sorted(colours.items(), key=lambda kv: -kv[1]):
        label = palette.get(code).name.replace("_", " ") if palette and code in palette else ""
        names.append(f"{label} ({code}) x {count}" if label else f"colour {code} x {count}")
    typer.echo(f"colours: {', '.join(names)}")
    if bricks:
        lo = np.array([[b.x, b.y, b.z] for b in bricks]).min(axis=0)
        hi = np.array([[b.x + b.w, b.y + b.h, b.z + b.d] for b in bricks]).max(axis=0)
        span = hi - lo
        typer.echo(
            f"size: {span[0] * STUD_MM / 10:.1f} x {span[2] * STUD_MM / 10:.1f} cm footprint, "
            f"{span[1] * PLATE_MM / 10:.1f} cm tall ({span[0]} x {span[2]} studs)"
        )
    typer.echo("stability: NOT CHECKED (connectivity and physics checks come in phase 2)")
    typer.echo("cost: not estimated (no price data until phase 3)")
    for note in notes:
        typer.secho(f"note: {note}", fg=typer.colors.YELLOW)


@app.command()
def library(
    part: str = typer.Option("3001", help="Part id to inspect."),
) -> None:
    """Check the LDraw library and report one part's origin and dimensions."""
    lib = _open_library()
    n_parts = sum(1 for p in (lib.root / "parts").iterdir() if p.suffix.lower() == ".dat")
    typer.echo(f"{LIBRARY_ENV} = {os.environ[LIBRARY_ENV]}")
    typer.echo(f"part files:  {n_parts} in parts/")
    typer.echo(f"colours:     {lib.ldconfig_path}")

    name = f"{part}.dat"
    try:
        lo, hi = lib.bounds(name)
        blo, bhi = lib.bounds(name, STUD_PRIMITIVES)
    except LibraryError as exc:
        raise _fail(str(exc)) from exc

    size = bhi - blo
    centre_x, centre_z = (blo[0] + bhi[0]) / 2, (blo[2] + bhi[2]) / 2
    typer.echo("")
    typer.echo(f"{lib.resolve(name)}: {lib.title(name)}")
    typer.echo(f"  bounds, studs included: {_fmt(lo)} to {_fmt(hi)} LDU")
    typer.echo(f"  body, studs excluded:   {_fmt(blo)} to {_fmt(bhi)} LDU")
    typer.echo(
        f"  body size: {size[0]:g} x {size[2]:g} LDU footprint (X by Z), {size[1]:g} LDU tall"
        f" = {size[0] * LDU_MM:g} x {size[2] * LDU_MM:g} x {size[1] * LDU_MM:g} mm"
    )
    typer.echo(f"  studs rise {blo[1] - lo[1]:g} LDU above the body (-Y is up)")
    typer.echo(
        f"  origin: footprint centre at x={centre_x:g}, z={centre_z:g};"
        f" body top at y={blo[1]:g}, body bottom at y={bhi[1]:g}"
    )
    if centre_x == 0 and centre_z == 0 and blo[1] == 0:
        typer.echo("  => the origin is the centre of the top face of the body")


@app.command("mesh")
def mesh_stage(mesh: Path = MeshArg, up: str = UpOpt, out: Path = OutOpt) -> None:
    """Stage 1 (file provider): load a mesh and write it Y up as <name>.mesh.glb."""
    loaded = _load(mesh, up)
    out.mkdir(parents=True, exist_ok=True)
    target = out / f"{_name(mesh)}.mesh.glb"
    loaded.export(target)
    typer.echo(f"{target}: {len(loaded.faces)} triangles, extents {_fmt(loaded.extents)}")


@app.command("voxelize")
def voxelize_stage(
    mesh: Path = MeshArg,
    size: int = SizeOpt,
    up: str = UpOpt,
    default_colour: int = ColourOpt,
    out: Path = OutOpt,
) -> None:
    """Stage 2: fill the mesh with coloured brick cells, written as <name>.voxels.npz."""
    grid = _voxelize(_load(mesh, up), size, _palette(), default_colour)
    out.mkdir(parents=True, exist_ok=True)
    target = out / f"{_name(mesh)}.voxels.npz"
    grid.save(target)
    nx, ny, nz = grid.shape
    typer.echo(f"{target}: {nx} x {nz} studs, {ny} layers, {int(grid.filled.sum())} cells filled")
    for note in grid.notes:
        typer.secho(f"note: {note}", fg=typer.colors.YELLOW)


@app.command("layout")
def layout_stage(
    voxels: Path = VoxelsArg,
    out: Path = OutOpt,
) -> None:
    """Stage 3: merge cells into bricks (greedy, largest first), written as <name>.layout.json."""
    grid = VoxelGrid.load(voxels)
    bricks = greedy_layout(grid)
    out.mkdir(parents=True, exist_ok=True)
    target = out / f"{_name(voxels)}.layout.json"
    save_layout(bricks, target, notes=grid.notes)
    typer.echo(f"{target}")
    _report(bricks, _optional_palette(), grid.notes)


@app.command("ldraw")
def ldraw_stage(
    layout: Path = LayoutArg,
    out: Path = OutOpt,
) -> None:
    """Write a layout as an LDraw model, <name>.ldr."""
    bricks, notes = load_layout(layout)
    out.mkdir(parents=True, exist_ok=True)
    name = _name(layout)
    target = out / f"{name}.ldr"
    write_model(bricks, target, title=name)
    typer.echo(f"{target}")
    _report(bricks, _optional_palette(), notes)


@app.command()
def build(
    mesh: Path = MeshArg,
    size: int = SizeOpt,
    up: str = UpOpt,
    default_colour: int = ColourOpt,
    out: Path = OutOpt,
) -> None:
    """Run every stage: mesh -> voxels -> layout -> LDraw model."""
    palette = _palette()
    loaded = _load(mesh, up)
    name = _name(mesh)
    out.mkdir(parents=True, exist_ok=True)
    loaded.export(out / f"{name}.mesh.glb")
    grid = _voxelize(loaded, size, palette, default_colour)
    grid.save(out / f"{name}.voxels.npz")
    bricks = greedy_layout(grid)
    save_layout(bricks, out / f"{name}.layout.json", notes=grid.notes)
    target = out / f"{name}.ldr"
    write_model(bricks, target, title=name)
    nx, ny, nz = grid.shape
    typer.echo(f"{mesh} -> {target}")
    typer.echo(f"grid: {nx} x {nz} studs, {ny} layers, {int(grid.filled.sum())} cells filled")
    _report(bricks, palette, grid.notes)


def _optional_palette() -> Palette | None:
    try:
        return Palette.from_ldconfig(LDrawLibrary.from_env().ldconfig_path)
    except LibraryError:
        return None
