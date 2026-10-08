# brickbuild

Turn a 3D mesh (later: a few photos) into a buildable brick model made of
LDraw compatible parts, with instructions and a parts list. See `CLAUDE.md`
for the full plan.

## Setup

```
uv sync
```

brickbuild needs the official LDraw parts library. Download
https://library.ldraw.org/library/updates/complete.zip and unzip it into
`vendor/` so that `vendor/ldraw/` directly contains `parts/`, `p/` and
`LDConfig.ldr`. Then copy `.env.example` to `.env`. The CLI loads `.env`
from the current folder or any parent, and relative paths in it are
resolved against the folder holding the file.

Check the setup:

```
uv run brickbuild library
```

## Development

```
uv run pytest
uv run ruff check . && uv run ruff format .
```

Tests that need the LDraw library are skipped when it is missing. Set
`BRICKBUILD_REQUIRE_LIBRARY=1` (CI does) to make them fail instead.
