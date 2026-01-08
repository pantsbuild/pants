# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""A tool to find common misspellings in text files.

See https://github.com/codespell-project/codespell for details.
"""

from __future__ import annotations

from typing import Iterable

from pants.backend.python.goals import lockfile as python_lockfile
from pants.backend.tools.codespell import rules as codespell_rules
from pants.backend.tools.codespell import subsystem as subsystem
from pants.engine.rules import Rule
from pants.engine.unions import UnionRule


def rules() -> Iterable[Rule | UnionRule]:
    return (
        *codespell_rules.rules(),
        *subsystem.rules(),
        *python_lockfile.rules(),
    )
