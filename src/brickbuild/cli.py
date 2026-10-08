"""Command line interface. One subcommand per pipeline stage."""

from __future__ import annotations

import os

import typer

from brickbuild import __version__
from brickbuild.env import LIBRARY_ENV, load_env
from brickbuild.ldraw import LDU_MM, STUD_PRIMITIVES, LDrawLibrary, LibraryError

app = typer.Typer(
    help="Turn a 3D mesh into a buildable brick model (LDraw compatible parts).",
    no_args_is_help=True,
    add_completion=False,
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


def _fmt(v) -> str:
    return "(" + ", ".join(f"{x:g}" for x in v) + ")"


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
