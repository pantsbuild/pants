# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
"""Make self-extractable archives on Unix

See https://github.com/megastep/makeself.
"""
from pants.backend.makeself import makeself
from pants.backend.makeself.goals import package, run
from pants.backend.makeself.target_types import MakeselfArchiveTarget
from pants.core.util_rules import system_binaries


def target_types():
    return [MakeselfArchiveTarget]


def rules():
    return [
        *makeself.rules(),
        *package.rules(),
        *run.rules(),
        *system_binaries.rules(),
    ]
