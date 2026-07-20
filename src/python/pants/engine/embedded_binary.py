# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import importlib.resources
import os


def get_embedded_binary(binary_name: str) -> str | None:
    """Return the path to a binary embedded in the pants wheel, or None if not present."""
    # In theory as_file could return a temporary file and clean it up, so we'd be returning
    # an invalid path. But in practice we know that we're running either in a venv with all
    # resources expanded on disk, or from sources, and either way we will get a persistent
    # valid path that will not be cleaned up.
    with importlib.resources.as_file(
        importlib.resources.files("pants.bin").joinpath(binary_name)
    ) as bin_path:
        if os.path.isfile(bin_path):
            os.chmod(bin_path, 0o755)
            return str(bin_path)
    return None
