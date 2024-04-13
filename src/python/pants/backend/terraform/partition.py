# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from collections import defaultdict
from typing import Iterable


def partition_files_by_directory(filepaths: Iterable[str]) -> dict[str, list[str]]:
    """Maps files to directories, since `terraform` operates on a directory-by-directory basis."""
    directories = defaultdict(list)
    for filepath in filepaths:
        directory = os.path.dirname(filepath) or "."
        directories[directory].append(filepath)

    return directories
