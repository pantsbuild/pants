# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from unittest.mock import MagicMock

from pants.backend.experimental.python.lockfile import (
    PythonLockfileRequest,
)
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.util.ordered_set import FrozenOrderedSet
from pants.backend.experimental.python.lockfile_metadata import lockfile_metadata_header, read_lockfile_metadata, validated_lockfile_content


def test_metadata_round_trip() -> None:
    val = "help_im_trapped_inside_a_unit_test_string"
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
    assert line_by_line(validated_lockfile_content(req, content)) == line_by_line(output)


def test_hex_digest_empty() -> None:
    req = PythonLockfileRequest(
        requirements=FrozenOrderedSet([]),
        interpreter_constraints=InterpreterConstraints([]),
        dest="lockfile.py",
        description="empty",
    )

    assert req.hex_digest == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def test_hex_digest_empty_interpreter_constraints() -> None:
    req = PythonLockfileRequest(
        requirements=FrozenOrderedSet(
            [
                "help",
                "meim",
                "trap",
                "pedi",
                "naun",
                "itte",
            ]
        ),
        interpreter_constraints=InterpreterConstraints([]),
        dest="lockfile.py",
        description="empty",
    )

    assert req.hex_digest == "9056af98e88b5f1ce893dcb7d7e189bd813ef4f5009f26594e1499be546fb3e1"


def test_hex_digest_empty_requirements() -> None:
    req = PythonLockfileRequest(
        requirements=FrozenOrderedSet([]),
        interpreter_constraints=InterpreterConstraints(
            ["stda", "tase", "tand", "itsd", "arka", "ndsc"]
        ),
        dest="lockfile.py",
        description="empty",
    )

    assert req.hex_digest == "312bd499be026b8ecedb95a3b3e234bdea28e82c2d40ae1b2a435fc20971e2c2"


def test_hex_digest_both_specified() -> None:
    req = PythonLockfileRequest(
        requirements=FrozenOrderedSet(["aryi", "nher", "eple", "ases", "avem"]),
        interpreter_constraints=InterpreterConstraints(
            [
                "efro",
                "mitq",
                "uick",
            ]
        ),
        dest="lockfile.py",
        description="empty",
    )

    assert req.hex_digest == "fc71e036ed72f43b9e0f2dcd37050a9e21773a619f0172ab8b657be9ee502fb6"
