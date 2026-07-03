# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import re

from pants_release.generate_github_workflows import (
    pants_interpreter_constraints,
    pinned_pex,
)


def test_pinned_pex_returns_valid_version_and_sha256() -> None:
    version, sha256 = pinned_pex()
    assert re.fullmatch(r"v\d+\.\d+\.\d+", version)
    assert re.fullmatch(r"[0-9a-f]{64}", sha256)


def test_pants_interpreter_constraints_are_valid() -> None:
    constraints = pants_interpreter_constraints()
    assert constraints
    assert all(isinstance(constraint, str) and constraint for constraint in constraints)
