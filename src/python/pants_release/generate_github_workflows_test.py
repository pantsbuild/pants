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
    values = read_pex_constants("PEX_VERSION", "PEX_BINARY_HASH")
    assert re.fullmatch(r"v\d+\.\d+\.\d+", values["PEX_VERSION"])
    assert re.fullmatch(r"[0-9a-fA-F]{64}", values["PEX_BINARY_HASH"])


@pytest.mark.parametrize(
    "source",
    [
        'PEX_VERSION = "v2.104.1"\n',
        'PEX_VERSION = "v2.104.1"\nPEX_BINARY_HASH = "invalid"\n',
        'PEX_VERSION = "invalid\nPEX_BINARY_HASH = "invalid"\n',
    ],
)
def test_pex_constants_reject_missing_or_malformed_assignments(tmp_path: Path, source: str) -> None:
    source_path = tmp_path / "pex_cli.py"
    source_path.write_text(source)
    with pytest.raises(ValueError, match="PEX_VERSION|PEX_BINARY_HASH"):
        read_pex_constants("PEX_VERSION", "PEX_BINARY_HASH", source_path=source_path)


def test_pex_constants_use_first_assignment(tmp_path: Path) -> None:
    source_path = tmp_path / "pex_cli.py"
    source_path.write_text('PEX_VERSION = "v2.104.1"\nPEX_VERSION = "v2.104.2"\n')
    assert read_pex_constants("PEX_VERSION", source_path=source_path) == {"PEX_VERSION": "v2.104.1"}


def test_pants_interpreter_constraints_are_valid() -> None:
    constraints = pants_interpreter_constraints()
    assert constraints
    assert all(isinstance(constraint, str) and constraint for constraint in constraints)
