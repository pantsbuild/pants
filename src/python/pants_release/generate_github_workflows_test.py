# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import re

import pytest
from pants_release.generate_github_workflows import (
    PEX_BINARY_HASH,
    PEX_VERSION,
    _parse_constant,
    pants_interpreter_constraints,
)


def test_pex_constants_from_backend_source() -> None:
    assert re.fullmatch(r"v\d+\.\d+\.\d+", PEX_VERSION)
    assert re.fullmatch(r"[0-9a-fA-F]{64}", PEX_BINARY_HASH)


@pytest.mark.parametrize(
    ("source", "name"),
    [
        ('PEX_VERSION = "v2.104.1"\n', "PEX_BINARY_HASH"),
        ("PEX_BINARY_HASH = invalid\n", "PEX_BINARY_HASH"),
        ('PEX_VERSION = "invalid\n', "PEX_VERSION"),
    ],
)
def test_pex_constant_rejects_missing_or_malformed_assignment(source: str, name: str) -> None:
    with pytest.raises(ValueError, match=name):
        _parse_constant(source, name)


def test_pex_constant_uses_first_assignment() -> None:
    source = 'PEX_VERSION = "v2.104.1"\nPEX_VERSION = "v2.104.2"\n'
    assert _parse_constant(source, "PEX_VERSION") == "v2.104.1"


def test_pex_constant_parser_does_not_validate_named_values() -> None:
    assert _parse_constant('PEX_BINARY_HASH = "invalid"\n', "PEX_BINARY_HASH") == "invalid"


def test_pants_interpreter_constraints_are_valid() -> None:
    constraints = pants_interpreter_constraints()
    assert constraints
    assert all(isinstance(constraint, str) and constraint for constraint in constraints)
