"""Write the acceptance fixture meshes for manual runs: python -m tests.fixtures [out_dir]"""

import sys
from pathlib import Path

from tests.fixtures.shapes import write_fixtures

out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("out/fixtures")
for name, path in write_fixtures(out).items():
    print(f"{name}: {path}")
