# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import importlib.resources
import os


def pants_lock_bin() -> str:
    """Return the path to the bundled pants_lock binary, or raise if not present.

    In theory as_file could return a temporary file and clean it up, so we'd be returning
    an invalid path. But in practice we know that we're running either in a venv with all
    resources expanded on disk, or from sources, and either way we will get a persistent
    valid path that will not be cleaned up.
    """
    with importlib.resources.as_file(
        importlib.resources.files("pants.bin").joinpath("pants_lock")
    ) as pants_lock_bin:
        if os.path.isfile(pants_lock_bin):
            os.chmod(pants_lock_bin, 0o755)
            return str(pants_lock_bin)
    raise Exception("Could not find pants_lock binary")
