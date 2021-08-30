# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from enum import Enum


# NB: This class is re-exported in pants.engine.fs as part of the public Plugin API.
#   Backend code in the Pants repo should import this class from there, to model idiomatic
#   use of that API. However this class is also used by code in base, core, and options, which
#   must not depend on pants.engine.fs, so those must import directly from here.
class GlobMatchErrorBehavior(Enum):
    """Describe the action to perform when matching globs in BUILD files to source files.

    NB: this object is interpreted from within Snapshot::lift_path_globs() -- that method will
    need to be aware of any changes to this object's definition.
    """

    ignore = "ignore"
    warn = "warn"
    error = "error"
