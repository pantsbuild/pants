# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pants_release.generate_github_workflows import (
    pants_interpreter_constraints,
    read_pex_constants,
)


def test_pex_constants_from_backend_source() -> None:
    version, binary_hash = read_pex_constants()
    assert re.fullmatch(r"v\d+\.\d+\.\d+", version)
    assert re.fullmatch(r"[0-9a-fA-F]{64}", binary_hash)


@pytest.mark.parametrize(
    "source",
    [
        'PEX_VERSION = "v2.104.1"\n',
        'PEX_VERSION = "v2.104.1"\nPEX_BINARY_HASH = "invalid"\n',
        'PEX_VERSION = "v2.104.1"\nPEX_VERSION = "v2.104.2"\n',
    ],
)
def test_pex_constants_reject_missing_malformed_or_duplicate_assignments(
    tmp_path: Path, source: str
) -> None:
    source_path = tmp_path / "pex_cli.py"
    source_path.write_text(source)
    with pytest.raises(ValueError, match="PEX_VERSION|PEX_BINARY_HASH"):
        read_pex_constants(source_path)


def test_pants_interpreter_constraints_are_valid() -> None:
    constraints = pants_interpreter_constraints()
    assert constraints
    assert all(isinstance(constraint, str) and constraint for constraint in constraints)
