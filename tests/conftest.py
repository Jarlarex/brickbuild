import os

import pytest

from brickbuild.env import load_env
from brickbuild.ldraw import LDrawLibrary, LibraryError

load_env()


@pytest.fixture(scope="session")
def library() -> LDrawLibrary:
    """The LDraw library from LDRAW_LIBRARY_PATH.

    Tests that need it are skipped when it is missing, unless
    BRICKBUILD_REQUIRE_LIBRARY is set (CI sets it), in which case they fail.
    """
    try:
        return LDrawLibrary.from_env()
    except LibraryError as exc:
        if os.environ.get("BRICKBUILD_REQUIRE_LIBRARY"):
            pytest.fail(f"LDraw library required but unavailable: {exc}")
        pytest.skip(f"LDraw library unavailable: {exc}")
