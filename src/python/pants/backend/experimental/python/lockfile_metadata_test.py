# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pants.backend.experimental.python.lockfile_metadata import (
    LockfileMetadata,
    calculate_invalidation_digest,
)
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.util.ordered_set import FrozenOrderedSet


def test_metadata_header_round_trip() -> None:
    input_metadata = LockfileMetadata(
        "cab0c0c0c0c0dadacafec0c0c0c0cafedadabeefc0c0c0c0feedbeeffeedbeef",
        InterpreterConstraints(["CPython==2.7.*", "PyPy", "CPython>=3.6,<4,!=3.7.*"]),
    )
    serialized_lockfile = input_metadata.add_header_to_lockfile(
        b"req1==1.0", regenerate_command="./pants lock"
    )
    output_metadata = LockfileMetadata.from_lockfile(serialized_lockfile)
    assert input_metadata == output_metadata


def test_add_header_to_lockfile() -> None:
    input_lockfile = b"""dave==3.1.4 \\
    --hash=sha256:cab0c0c0c0c0dadacafec0c0c0c0cafedadabeefc0c0c0c0feedbeeffeedbeef \\
    """

    expected = b"""
# This lockfile was autogenerated by Pants. To regenerate, run:
#
#    ./pants lock
#
# --- BEGIN PANTS LOCKFILE METADATA: DO NOT EDIT OR REMOVE ---
# {
#   "requirements_invalidation_digest": "000faaafcacacaca",
#   "valid_for_interpreter_constraints": [
#     "CPython>=3.7"
#   ]
# }
# --- END PANTS LOCKFILE METADATA ---
dave==3.1.4 \\
    --hash=sha256:cab0c0c0c0c0dadacafec0c0c0c0cafedadabeefc0c0c0c0feedbeeffeedbeef \\
    """

    def line_by_line(b: bytes) -> list[bytes]:
        return [i for i in (j.strip() for j in b.splitlines()) if i]

    metadata = LockfileMetadata("000faaafcacacaca", InterpreterConstraints([">=3.7"]))
    result = metadata.add_header_to_lockfile(input_lockfile, regenerate_command="./pants lock")
    assert line_by_line(result) == line_by_line(expected)


_requirements = ["flake8-pantsbuild>=2.0,<3", "flake8-2020>=1.6.0,<1.7.0"]


@pytest.mark.parametrize(
    "requirements,expected",
    [
        ([], "c8e8d0a6d6ec36bee3942091046d81d86e3b83b143b37a7cc714e2d022bf4f85"),
        (_requirements, "66327c52225d2f798ffad7f092bf1b51da8a66777f3ebf654e2444d7eb1429f4"),
    ],
)
def test_invalidation_digest(requirements, expected) -> None:
    assert calculate_invalidation_digest(FrozenOrderedSet(requirements)) == expected


@pytest.mark.parametrize(
    "user_digest, expected_digest, user_ic, expected_ic, matches",
    [
        (
            "yes",
            "yes",
            [">=3.5.5"],
            [">=3.5, <=3.6"],
            False,
        ),  # User ICs contain versions in the 3.6 range
        ("yes", "yes", [">=3.5.5, <=3.5.10"], [">=3.5, <=3.6"], True),
        ("yes", "no", [">=3.5.5, <=3.5.10"], [">=3.5, <=3.6"], False),  # Digests do not match
        (
            "yes",
            "yes",
            [">=3.5.5, <=3.5.10"],
            [">=3.5", "<=3.6"],
            True,
        ),  # User ICs match each of the actual ICs individually
        (
            "yes",
            "yes",
            [">=3.5.5, <=3.5.10"],
            [">=3.5", "<=3.5.4"],
            True,
        ),  # User ICs do not match one of the individual ICs
        ("yes", "yes", ["==3.5.*, !=3.5.10"], [">=3.5, <=3.6"], True),
        (
            "yes",
            "yes",
            ["==3.5.*"],
            [">=3.5, <=3.6, !=3.5.10"],
            False,
        ),  # Excluded IC from expected range is valid for user ICs
        ("yes", "yes", [">=3.5, <=3.6", ">= 3.8"], [">=3.5"], True),
        (
            "yes",
            "yes",
            [">=3.5, <=3.6", ">= 3.8"],
            [">=3.5, !=3.7.10"],
            True,
        ),  # Excluded version from expected ICs is not in a range specified
    ],
)
def test_is_valid_for(user_digest, expected_digest, user_ic, expected_ic, matches) -> None:
    m = LockfileMetadata(expected_digest, InterpreterConstraints(expected_ic))
    assert (
        m.is_valid_for(
            user_digest,
            InterpreterConstraints(user_ic),
            ["2.7", "3.5", "3.6", "3.7", "3.8", "3.9", "3.10"],
        )
        == matches
    )
