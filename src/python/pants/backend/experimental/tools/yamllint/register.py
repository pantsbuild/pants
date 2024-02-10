# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
"""A configurable linter for YAML files.

See https://yamllint.readthedocs.io/ for details.
"""

from __future__ import annotations

from typing import Iterable

from pants.backend.python.goals import lockfile as python_lockfile
from pants.backend.tools.yamllint import rules as yamllint_rules
from pants.backend.tools.yamllint import subsystem as subsystem
from pants.engine.rules import Rule
from pants.engine.unions import UnionRule


def rules() -> Iterable[Rule | UnionRule]:
    return (
        *yamllint_rules.rules(),
        *subsystem.rules(),
        *python_lockfile.rules(),
    )
