# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from typing import List

import pytest
from pkg_resources import Requirement

from pants.backend.python.target_types import InterpreterConstraintsField
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.build_graph.address import Address
from pants.engine.target import FieldSet
from pants.python.python_setup import PythonSetup
from pants.testutil.option_util import create_subsystem
from pants.util.frozendict import FrozenDict


@dataclass(frozen=True)
class MockFieldSet(FieldSet):
    interpreter_constraints: InterpreterConstraintsField

    @classmethod
    def create_for_test(cls, address: Address, compat: str | None) -> MockFieldSet:
        return cls(
            address=address,
            interpreter_constraints=InterpreterConstraintsField(
                [compat] if compat else None, address=address
            ),
        )


def test_merge_interpreter_constraints() -> None:
    def assert_merged(*, inp: List[List[str]], expected: List[str]) -> None:
        result = sorted(str(req) for req in InterpreterConstraints.merge_constraint_sets(inp))
        # Requirement.parse() sorts specs differently than we'd like, so we convert each str to a
        # Requirement.
        normalized_expected = sorted(str(Requirement.parse(v)) for v in expected)
        assert result == normalized_expected

    # Multiple constraint sets get merged so that they are ANDed.
    # A & B => A & B
    assert_merged(inp=[["CPython==2.7.*"], ["CPython==3.6.*"]], expected=["CPython==2.7.*,==3.6.*"])

    # Multiple constraints within a single constraint set are kept separate so that they are ORed.
    # A | B => A | B
    assert_merged(
        inp=[["CPython==2.7.*", "CPython==3.6.*"]], expected=["CPython==2.7.*", "CPython==3.6.*"]
    )

    # Input constraints already were ANDed.
    # A => A
    assert_merged(inp=[["CPython>=2.7,<3"]], expected=["CPython>=2.7,<3"])

    # Both AND and OR.
    # (A | B) & C => (A & B) | (B & C)
    assert_merged(
        inp=[["CPython>=2.7,<3", "CPython>=3.5"], ["CPython==3.6.*"]],
        expected=["CPython>=2.7,<3,==3.6.*", "CPython>=3.5,==3.6.*"],
    )
    # A & B & (C | D) => (A & B & C) | (A & B & D)
    assert_merged(
        inp=[["CPython==2.7.*"], ["CPython==3.6.*"], ["CPython==3.7.*", "CPython==3.8.*"]],
        expected=["CPython==2.7.*,==3.6.*,==3.7.*", "CPython==2.7.*,==3.6.*,==3.8.*"],
    )
    # (A | B) & (C | D) => (A & C) | (A & D) | (B & C) | (B & D)
    assert_merged(
        inp=[["CPython>=2.7,<3", "CPython>=3.5"], ["CPython==3.6.*", "CPython==3.7.*"]],
        expected=[
            "CPython>=2.7,<3,==3.6.*",
            "CPython>=2.7,<3,==3.7.*",
            "CPython>=3.5,==3.6.*",
            "CPython>=3.5,==3.7.*",
        ],
    )
    # A & (B | C | D) & (E | F) & G =>
    # (A & B & E & G) | (A & B & F & G) | (A & C & E & G) | (A & C & F & G) | (A & D & E & G) | (A & D & F & G)
    assert_merged(
        inp=[
            ["CPython==3.6.5"],
            ["CPython==2.7.14", "CPython==2.7.15", "CPython==2.7.16"],
            ["CPython>=3.6", "CPython==3.5.10"],
            ["CPython>3.8"],
        ],
        expected=[
            "CPython==2.7.14,==3.5.10,==3.6.5,>3.8",
            "CPython==2.7.14,>=3.6,==3.6.5,>3.8",
            "CPython==2.7.15,==3.5.10,==3.6.5,>3.8",
            "CPython==2.7.15,>=3.6,==3.6.5,>3.8",
            "CPython==2.7.16,==3.5.10,==3.6.5,>3.8",
            "CPython==2.7.16,>=3.6,==3.6.5,>3.8",
        ],
    )

    # Deduplicate between constraint_sets
    # (A | B) & (A | B) => A | B. Naively, this should actually resolve as follows:
    #   (A | B) & (A | B) => (A & A) | (A & B) | (B & B) => A | (A & B) | B.
    # But, we first deduplicate each constraint_set.  (A | B) & (A | B) can be rewritten as
    # X & X => X.
    assert_merged(
        inp=[["CPython==2.7.*", "CPython==3.6.*"], ["CPython==2.7.*", "CPython==3.6.*"]],
        expected=["CPython==2.7.*", "CPython==3.6.*"],
    )
    # (A | B) & C & (A | B) => (A & C) | (B & C). Alternatively, this can be rewritten as
    # X & Y & X => X & Y.
    assert_merged(
        inp=[
            ["CPython>=2.7,<3", "CPython>=3.5"],
            ["CPython==3.6.*"],
            ["CPython>=3.5", "CPython>=2.7,<3"],
        ],
        expected=["CPython>=2.7,<3,==3.6.*", "CPython>=3.5,==3.6.*"],
    )

    # No specifiers
    assert_merged(inp=[["CPython"]], expected=["CPython"])
    assert_merged(inp=[["CPython"], ["CPython==3.7.*"]], expected=["CPython==3.7.*"])

    # No interpreter is shorthand for CPython, which is how Pex behaves
    assert_merged(inp=[[">=3.5"], ["CPython==3.7.*"]], expected=["CPython>=3.5,==3.7.*"])

    # Different Python interpreters, which are guaranteed to fail when ANDed but are safe when ORed.
    with pytest.raises(ValueError):
        InterpreterConstraints.merge_constraint_sets([["CPython==3.7.*"], ["PyPy==43.0"]])
    assert_merged(inp=[["CPython==3.7.*", "PyPy==43.0"]], expected=["CPython==3.7.*", "PyPy==43.0"])

    # Ensure we can handle empty input.
    assert_merged(inp=[], expected=[])


@pytest.mark.parametrize(
    "constraints",
    [
        ["CPython>=2.7,<3"],
        ["CPython>=2.7,<3", "CPython>=3.6"],
        ["CPython>=2.7.13"],
        ["CPython>=2.7.13,<2.7.16"],
        ["CPython>=2.7.13,!=2.7.16"],
        ["PyPy>=2.7,<3"],
    ],
)
def test_interpreter_constraints_includes_python2(constraints) -> None:
    assert InterpreterConstraints(constraints).includes_python2() is True


@pytest.mark.parametrize(
    "constraints",
    [
        ["CPython>=3.6"],
        ["CPython>=3.7"],
        ["CPython>=3.6", "CPython>=3.8"],
        ["CPython!=2.7.*"],
        ["PyPy>=3.6"],
    ],
)
def test_interpreter_constraints_do_not_include_python2(constraints):
    assert InterpreterConstraints(constraints).includes_python2() is False


@pytest.mark.parametrize(
    "constraints,expected",
    [
        (["CPython>=2.7"], "2.7"),
        (["CPython>=3.5"], "3.5"),
        (["CPython>=3.6"], "3.6"),
        (["CPython>=3.7"], "3.7"),
        (["CPython>=3.8"], "3.8"),
        (["CPython>=3.9"], "3.9"),
        (["CPython>=3.10"], "3.10"),
        (["CPython==2.7.10"], "2.7"),
        (["CPython==3.5.*", "CPython>=3.6"], "3.5"),
        (["CPython==2.6.*"], None),
    ],
)
def test_interpreter_constraints_minimum_python_version(
    constraints: List[str], expected: str
) -> None:
    assert InterpreterConstraints(constraints).minimum_python_version() == expected


@pytest.mark.parametrize(
    "constraints",
    [
        ["CPython==3.8.*"],
        ["CPython==3.8.1"],
        ["CPython==3.9.1"],
        ["CPython>=3.8"],
        ["CPython>=3.9"],
        ["CPython>=3.10"],
        ["CPython==3.8.*", "CPython==3.9.*"],
        ["PyPy>=3.8"],
    ],
)
def test_interpreter_constraints_require_python38(constraints) -> None:
    assert InterpreterConstraints(constraints).requires_python38_or_newer() is True


@pytest.mark.parametrize(
    "constraints",
    [
        ["CPython==3.5.*"],
        ["CPython==3.6.*"],
        ["CPython==3.7.*"],
        ["CPython==3.7.3"],
        ["CPython>=3.7"],
        ["CPython==3.7.*", "CPython==3.8.*"],
        ["CPython==3.5.3", "CPython==3.8.3"],
        ["PyPy>=3.7"],
    ],
)
def test_interpreter_constraints_do_not_require_python38(constraints):
    assert InterpreterConstraints(constraints).requires_python38_or_newer() is False


def test_group_field_sets_by_constraints() -> None:
    py2_fs = MockFieldSet.create_for_test(Address("", target_name="py2"), ">=2.7,<3")
    py3_fs = [
        MockFieldSet.create_for_test(Address("", target_name="py3"), "==3.6.*"),
        MockFieldSet.create_for_test(Address("", target_name="py3_second"), "==3.6.*"),
    ]
    no_constraints_fs = MockFieldSet.create_for_test(
        Address("", target_name="no_constraints"), None
    )
    assert InterpreterConstraints.group_field_sets_by_constraints(
        [py2_fs, *py3_fs, no_constraints_fs],
        python_setup=create_subsystem(PythonSetup, interpreter_constraints=[]),
    ) == FrozenDict(
        {
            InterpreterConstraints(): (no_constraints_fs,),
            InterpreterConstraints(["CPython>=2.7,<3"]): (py2_fs,),
            InterpreterConstraints(["CPython==3.6.*"]): tuple(py3_fs),
        }
    )


def test_group_field_sets_by_constraints_with_unsorted_inputs() -> None:
    py3_fs = [
        MockFieldSet.create_for_test(
            Address("src/python/a_dir/path.py", target_name="test"), "==3.6.*"
        ),
        MockFieldSet.create_for_test(
            Address("src/python/b_dir/path.py", target_name="test"), ">2.7,<3"
        ),
        MockFieldSet.create_for_test(
            Address("src/python/c_dir/path.py", target_name="test"), "==3.6.*"
        ),
    ]

    ic_36 = InterpreterConstraints([Requirement.parse("CPython==3.6.*")])

    output = InterpreterConstraints.group_field_sets_by_constraints(
        py3_fs,
        python_setup=create_subsystem(PythonSetup, interpreter_constraints=[]),
    )

    assert output[ic_36] == (
        MockFieldSet.create_for_test(
            Address("src/python/a_dir/path.py", target_name="test"), "==3.6.*"
        ),
        MockFieldSet.create_for_test(
            Address("src/python/c_dir/path.py", target_name="test"), "==3.6.*"
        ),
    )
