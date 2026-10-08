# CLAUDE.md

Project guide for Claude Code. Read this fully before writing any code.

## What we are building

A tool that takes a few photos of an object and produces a buildable toy brick model: a real parts layout that holds together, a step by step instruction manual (PDF), and a parts list that can be ordered.

Working title: `brickbuild`. Do not put "LEGO" in the package name, CLI name, UI, or any branding. Refer to "bricks" or "LDraw compatible parts" in user facing text.

## Core principle

This is a pipeline, not one AI model. The AI stage (images to 3D mesh) is the easy part and is treated as a swappable provider. The value of this project is in stages 2 to 5: turning a shape into connected, stable, orderable bricks with clear instructions. Spend the effort there.

```
images -> [1 mesh] -> [2 voxels] -> [3 brick layout] -> [4 stability] -> [5 instructions + parts list]
                                          ^                    |
                                          +---- re-tile -------+
```

Every stage reads and writes a plain file so each can be run, tested and debugged on its own.

## Tech stack

- Python 3.12, managed with `uv`
- `trimesh`, `numpy`, `scipy` for geometry
- `typer` for the CLI
- `pytest` for tests, `ruff` for lint and format
- LDraw (`.ldr` / `.mpd`) as the single model interchange format
- LPub3D for manual rendering (external tool, called from the CLI)
- Later phases only: FastAPI plus a Three.js viewer for a web UI

Do not add a dependency without saying why in the commit message.

## Repo layout

```
src/brickbuild/
  cli.py            # typer entry point, one subcommand per stage
  parts.py          # part catalogue: ids, footprints, heights
  colours.py        # palette loading and nearest colour matching
  mesh/             # stage 1 providers (file loader first, AI providers later)
  voxel.py          # stage 2
  layout/           # stage 3: merge, optimise, surface refinement
  stability/        # stage 4: connectivity graph, physics check
  ldraw.py          # LDraw read and write
  instructions.py   # stage 5: step ordering, submodels
  bom.py            # parts list exports
  modules/          # phase 6: functional modules (wheels etc.)
tests/
  fixtures/         # generated procedurally, not committed binaries
docs/
```

## Domain facts (do not guess these)

Units:
- 1 LDU = 0.4 mm
- 1 stud pitch = 20 LDU = 8 mm
- 1 brick height = 24 LDU = 9.6 mm
- 1 plate height = 8 LDU = 3.2 mm (3 plates = 1 brick)

LDraw:
- Negative Y is up.
- Part line: `1 <colour> <x> <y> <z> <a> <b> <c> <d> <e> <f> <g> <h> <i> <part>.dat`
- Step break: `0 STEP`
- Confirm each part's origin by reading its `.dat` file in the LDraw library. Never assume it.
- Load the colour palette from the library's `LDConfig.ldr`. Do not hardcode colour tables.
- Library path comes from the `LDRAW_LIBRARY_PATH` environment variable.

Starter part set (phase 1, bricks only):

| Size | Part | Size | Part |
|------|------|------|------|
| 1x1 | 3005 | 2x2 | 3003 |
| 1x2 | 3004 | 2x3 | 3002 |
| 1x3 | 3622 | 2x4 | 3001 |
| 1x4 | 3010 | 2x6 | 2456 |
| 1x6 | 3009 | 2x8 | 3007 |
| 1x8 | 3008 |     |      |

Plates for later phases: 3024 (1x1), 3023 (1x2), 3623 (1x3), 3710 (1x4), 3022 (2x2), 3021 (2x3), 3020 (2x4).

Colour ids differ between LDraw and BrickLink. Keep one mapping table in `colours.py` sourced from the Rebrickable colours data and cover it with a test.

## Data model

One internal representation, used by every stage after voxelisation:

```python
@dataclass(frozen=True)
class Brick:
    part: str  # LDraw part id, e.g. "3001"
    x: int  # stud grid position of the min corner
    y: int  # layer index, 0 = ground (in plate units once plates exist)
    z: int
    w: int  # footprint in studs after rotation
    d: int
    h: int  # height in plate units (brick = 3)
    rot: int  # 0 or 90 degrees about the vertical axis
    colour: int  # LDraw colour code
```

Conversion to LDraw coordinates happens only in `ldraw.py`.

## Build phases

Work through these in order. Do not start a phase until the previous one meets its acceptance check. Stop and report at the end of each phase.

### Phase 0: scaffold
`uv` project, CLI skeleton, ruff, pytest, CI workflow.
Accept: `uv run brickbuild --help` works, `uv run pytest` passes.

### Phase 1: mesh to bricks to LDraw (the thin end to end slice)
- Load `.glb` / `.obj` / `.stl`, scale to a target size in studs (`--size`, default 32 on the longest side).
- Voxelise at 8 x 8 x 9.6 mm cells. Fill solid first.
- Sample colour from the mesh texture or vertex colours and snap to the nearest palette colour in CIELAB space.
- Greedy merge of same colour cells into the starter parts, largest first.
- Write a valid `.ldr`.
Accept: a procedurally generated sphere, cube and arch each produce an `.ldr` that opens correctly in LeoCAD or BrickLink Studio, with zero overlapping bricks (tested).

### Phase 2: layout quality and sturdiness
- Build a connection graph: bricks are nodes, stud to tube contact between adjacent layers are edges.
- Connectivity check: every brick must reach the ground layer through the graph. Floating bricks are an error, not a warning.
- Layout optimisation: cost function that rewards overlap across layers and penalises vertically aligned seams and 1x1 parts. Start with greedy plus local search (split and re-merge a region, keep if cost improves).
- Physics check: static equilibrium per brick under gravity, with a limit on the pull a stud connection can resist. Before writing this from scratch, read the stability analysis in the BrickGPT repo (github.com/AvaLovelace1/BrickGPT, MIT licence) and reuse or port it. Its exact solver needs Gurobi, so provide a fallback that runs without it.
- Repair loop: for each failing brick, re-tile its neighbourhood and retest, up to a retry limit, then report what could not be fixed.
- Hollowing: remove interior cells while keeping a shell at least 2 studs thick, and re-run stability afterwards.
- Check the centre of mass falls inside the footprint of the base.
Accept: an unsupported overhang fixture is detected as unstable; the arch fixture passes; the optimised layout has a measurably lower seam score than the phase 1 greedy layout on all fixtures.

### Phase 3: instructions and parts list
- Order steps bottom up. Within a layer, group by region so each step adds a small number of parts (target 3 to 8).
- A step must never require placing a brick under an already placed brick or into a gap that cannot be reached.
- Split large models into submodels in an `.mpd`.
- Render the manual with LPub3D. Read its documentation for the current command line export options. Do not guess flags.
- Exports: CSV parts list, BrickLink wanted list XML, total part count, distinct part count.
- Flag part and colour combinations that do not exist in production (use Rebrickable data).
Accept: one command takes a mesh and produces an `.mpd`, a PDF manual, and both parts lists.

### Phase 4: image input
- Define a `MeshProvider` interface: `generate(images: list[Path]) -> Path`.
- Providers: `file` (exists from phase 1), then one AI provider. First choice is TRELLIS.2 (MIT licence). Check the licence of any other model before adding it, since some exclude the EU.
- Preprocess: background removal and consistent framing.
- Support both local GPU and a hosted endpoint behind the same interface. Keys come from environment variables, never from the repo.
Accept: 1 to 4 photos of a simple object produce a manual end to end.

### Phase 5: surface refinement
Plates (layer height becomes 3.2 mm), slopes and tiles on the outer surface. Stability must be re-run after every refinement pass.

### Phase 6: functionality
Mechanisms are not inferred from geometry. Approach:
- A vision model labels the object and its functional regions (for example "car, four wheels at these positions").
- Hand designed parametric modules in `modules/` are inserted into reserved volume, and the static layout is built around them.
- First and only module to start: wheel and axle assembly.

### Phase 7: web UI
Upload, 3D preview, size and detail controls, manual download.

## Commands

```
uv sync
uv run pytest
uv run ruff check . && uv run ruff format .
uv run brickbuild build <mesh-or-images> --size 32 --out out/
```

## Working rules

- Tests first for geometry and layout code. Every bug gets a regression test.
- Generate test fixtures with `trimesh` primitives inside the tests. Do not commit binary meshes.
- Never report a model as stable unless the stability check actually ran and passed. If a check was skipped or fell back to the simpler method, say so in the output.
- "Stable" in this project means it passes our analysis. It is not a guarantee about a physical build, and user facing text must not claim otherwise.
- Keep part count and cost visible. Print total parts and distinct parts after every build. Prefer common parts over rare ones when the cost function is otherwise tied.
- Use metric units everywhere. Prices in euro.
- Verify external tool behaviour (LPub3D, LDraw library layout, model APIs) from current documentation rather than memory.
- Do not download model weights or large files without asking first.
- Small commits, one concern each. Run tests and ruff before every commit.
- No em dashes in docs, comments, commit messages or replies.
- If a requirement here conflicts with what you find in practice, stop and ask rather than quietly working around it.
