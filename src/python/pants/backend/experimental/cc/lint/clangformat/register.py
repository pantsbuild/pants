# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
"""A formatter for C/C++ (and several other languages).

See https://clang.llvm.org/docs/ClangFormat.html for details.
"""

from __future__ import annotations

from typing import Iterable

from pants.backend.cc.lint.clangformat import rules as clangformat_rules
from pants.backend.cc.lint.clangformat import skip_field, subsystem
from pants.backend.python.goals import lockfile as python_lockfile
from pants.engine.rules import Rule
from pants.engine.unions import UnionRule


def rules() -> Iterable[Rule | UnionRule]:
    return (
        *clangformat_rules.rules(),
        *skip_field.rules(),
        *subsystem.rules(),
        *python_lockfile.rules(),
    )
