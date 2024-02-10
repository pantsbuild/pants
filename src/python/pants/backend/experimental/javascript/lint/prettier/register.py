# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
"""A formatter for JS/TS (and several other languages).

See https://prettier.io/ for details.
"""

from __future__ import annotations

from typing import Iterable

from pants.backend.javascript.lint.prettier import rules as prettier_rules
from pants.backend.javascript.lint.prettier import skip_field
from pants.backend.javascript.subsystems import nodejs
from pants.engine.rules import Rule
from pants.engine.unions import UnionRule


def rules() -> Iterable[Rule | UnionRule]:
    return (
        *nodejs.rules(),
        *prettier_rules.rules(),
        *skip_field.rules(),
    )
