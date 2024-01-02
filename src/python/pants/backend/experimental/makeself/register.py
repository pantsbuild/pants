# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.core.util_rules import system_binaries

from . import makeself
from .goals import package, run
from .target_types import MakeselfArchiveTarget


def target_types():
    return [MakeselfArchiveTarget]


def rules():
    return [
        *makeself.rules(),
        *package.rules(),
        *run.rules(),
        *system_binaries.rules(),
    ]
