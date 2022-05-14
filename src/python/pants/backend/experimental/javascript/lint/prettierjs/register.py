# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""A formatter for JS/TS (and several other languages).

See https://prettier.io/ for details.
"""

from __future__ import annotations

from typing import Iterable

from pants.backend.javascript.lint.prettierjs import rules as prettierjs_rules

# from pants.backend.javascript.lint.prettierjs import subsystem
from pants.engine.rules import Rule
from pants.engine.unions import UnionRule


def rules() -> Iterable[Rule | UnionRule]:
    return (
        *prettierjs_rules.rules(),
        # *skip_field.rules(),
        # *subsystem.rules(),
    )
