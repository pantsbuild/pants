# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants_release.generate_github_workflows import pants_interpreter_constraints


def test_pants_interpreter_constraints_are_valid() -> None:
    constraints = pants_interpreter_constraints()
    assert constraints
    assert all(isinstance(constraint, str) and constraint for constraint in constraints)
