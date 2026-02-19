# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Linter and formatter for JavaScript/TypeScript.

See https://eslint.org/ for details.
"""

from __future__ import annotations

from collections.abc import Iterable

from pants.backend.experimental.javascript.lint.eslint import rules as eslint_rules
from pants.backend.experimental.javascript.lint.eslint import skip_field
from pants.backend.javascript.subsystems import nodejs
from pants.engine.rules import Rule
from pants.engine.unions import UnionRule


def rules() -> Iterable[Rule | UnionRule]:
    return (
        *nodejs.rules(),
        *eslint_rules.rules(),
        *skip_field.rules(),
    )
