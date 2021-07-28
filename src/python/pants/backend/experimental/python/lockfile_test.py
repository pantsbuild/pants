# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from unittest.mock import MagicMock

import pytest

from pants.backend.experimental.python.lockfile import PythonLockfileRequest
from pants.backend.experimental.python.lockfile_metadata import (
    lockfile_content_with_header,
    lockfile_metadata_header,
    read_lockfile_metadata,
)
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.util.ordered_set import FrozenOrderedSet


def test_metadata_round_trip() -> None:
    val = "help_i_am_trapped_inside_a_unit_test_string"
    output = read_lockfile_metadata(lockfile_metadata_header(val))
    assert val == output.invalidation_digest


def test_validated_lockfile_content() -> None:
    req = MagicMock(hex_digest="000faaafcacacaca")
    content = b"""dave==3.1.4 \\
    --hash=sha256:cab0c0c0c0c0dadacafec0c0c0c0cafedadabeefc0c0c0c0feedbeeffeedbeef \\
    """

    output = b"""
# --- BEGIN PANTS LOCKFILE METADATA: DO NOT EDIT OR REMOVE ---
# invalidation digest: 000faaafcacacaca
# --- END PANTS LOCKFILE METADATA ---
dave==3.1.4 \\
    --hash=sha256:cab0c0c0c0c0dadacafec0c0c0c0cafedadabeefc0c0c0c0feedbeeffeedbeef \\
    """

    # Helper function to make the test case more resilient to reformatting
    line_by_line = lambda b: [ii for i in b.splitlines() if (ii := i.strip())]
    assert line_by_line(lockfile_content_with_header(req, content)) == line_by_line(output)


_interpreter_constraints = [">=3.7", "<3.10"]
_requirements = ["flake8-pantsbuild>=2.0,<3", "flake8-2020>=1.6.0,<1.7.0"]


@pytest.mark.parametrize(
    "requirements,interpreter_constraints,expected",
    [
        ([], [], "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"),
        (
            _interpreter_constraints,
            [],
            "04a2a2691d10bde0a2320bf32e2d40c60d0db511613fabc71933137c87f61500",
        ),
        ([], _requirements, "4ffd0a2a29407ce3f6bf7bfca60fdfc6f7d6224adda3c62807eb86666edf93bf"),
        (
            _interpreter_constraints,
            _requirements,
            "6c63e6595f2f6827b6c1b53b186a2fa2020942bbfe989e25059a493b32a8bf36",
        ),
    ],
)
def test_hex_digest(requirements, interpreter_constraints, expected) -> None:
    req = PythonLockfileRequest(
        requirements=FrozenOrderedSet(requirements),
        interpreter_constraints=InterpreterConstraints(interpreter_constraints),
        dest="lockfile.py",
        description="empty",
    )

    assert req.hex_digest == expected
