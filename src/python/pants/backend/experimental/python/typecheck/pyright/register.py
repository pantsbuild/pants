# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Static type checker for Python, running on NodeJS.

See https://github.com/Microsoft/pyright for details.
"""

from __future__ import annotations

from typing import Iterable

from pants.backend.javascript.subsystems import nodejs
from pants.backend.python.typecheck.pyright import rules as pyright_rules
from pants.backend.python.typecheck.pyright import skip_field
from pants.engine.rules import Rule
from pants.engine.unions import UnionRule


def rules() -> Iterable[Rule | UnionRule]:
    return (
        *nodejs.rules(),
        *pyright_rules.rules(),
        *skip_field.rules(),
    )
