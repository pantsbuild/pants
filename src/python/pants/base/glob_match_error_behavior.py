# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from enum import Enum


class GlobMatchErrorBehavior(Enum):
    """Describe the action to perform when matching globs in BUILD files to source files.

    NB: this object is interpreted from within Snapshot::lift_path_globs() -- that method will
    need to be aware of any changes to this object's definition.
    """

    ignore = "ignore"
    warn = "warn"
    error = "error"
