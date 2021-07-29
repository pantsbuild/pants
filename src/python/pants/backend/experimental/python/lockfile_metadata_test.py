# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pants.backend.experimental.python.lockfile_metadata import (
    invalidation_digest,
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
    line_by_line = lambda b: [i for i in (j.strip() for j in b.splitlines()) if i]
    assert line_by_line(lockfile_content_with_header("000faaafcacacaca", content)) == line_by_line(
        output
    )


_interpreter_constraints = [">=3.7", "<3.10"]
_requirements = ["flake8-pantsbuild>=2.0,<3", "flake8-2020>=1.6.0,<1.7.0"]


@pytest.mark.parametrize(
    "requirements,interpreter_constraints,expected",
    [
        ([], [], "51f5289473089f1de64ab760af3f03ff55cd769f25cce7ea82dd1ac88aac5ff4"),
        (
            _interpreter_constraints,
            [],
            "821e8eef80573c7d2460185da4d436b6a8c59e134f5f0758000be3c85e9819eb",
        ),
        ([], _requirements, "604fb99ed6d6d83ba2c4eb1230184dd7f279a446cda042e9e87099448f28dddb"),
        (
            _interpreter_constraints,
            _requirements,
            "9264a3b59a592d7eeac9cb4bbb4f5b2200907694bfe92b48757c99b1f71485f0",
        ),
    ],
)
def test_hex_digest(requirements, interpreter_constraints, expected) -> None:
    print(
        invalidation_digest(
            FrozenOrderedSet(requirements), InterpreterConstraints(interpreter_constraints)
        )
    )
    assert (
        invalidation_digest(
            FrozenOrderedSet(requirements), InterpreterConstraints(interpreter_constraints)
        )
        == expected
    )


def test_hash_depends_on_requirement_source():
    reqs = ["CPython"]
    assert invalidation_digest(
        FrozenOrderedSet(reqs), InterpreterConstraints([])
    ) != invalidation_digest(FrozenOrderedSet([]), InterpreterConstraints(reqs))
