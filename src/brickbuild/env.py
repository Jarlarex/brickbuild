"""Loading of local configuration from a .env file."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

LIBRARY_ENV = "LDRAW_LIBRARY_PATH"


def load_env() -> Path | None:
    """Load the nearest .env file, searching from the current directory upwards.

    Variables already set in the environment win over the file. A relative
    LDRAW_LIBRARY_PATH taken from the file is resolved against the folder that
    holds the file, so `.env` works no matter where the CLI is run from.
    Returns the path of the loaded file, or None if there was none.
    """
    found = find_dotenv(usecwd=True)
    if not found:
        return None
    env_file = Path(found)
    already_set = LIBRARY_ENV in os.environ
    load_dotenv(env_file, override=False)
    value = os.environ.get(LIBRARY_ENV)
    if not already_set and value and not Path(value).is_absolute():
        os.environ[LIBRARY_ENV] = str((env_file.parent / value).resolve())
    return env_file
