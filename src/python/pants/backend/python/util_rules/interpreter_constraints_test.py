# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pytest
from pkg_resources import Requirement

from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import (
    InterpreterConstraintsField,
    PythonSourcesGeneratorTarget,
    PythonSourceTarget,
)
from pants.backend.python.util_rules.interpreter_constraints import (
    _PATCH_VERSION_UPPER_BOUND,
    InterpreterConstraints,
)
from pants.build_graph.address import Address
from pants.engine.target import CoarsenedTarget, FieldSet, Target
from pants.testutil.option_util import create_subsystem
from pants.util.frozendict import FrozenDict
from pants.util.ordered_set import FrozenOrderedSet


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
    def assert_merged(*, inp: list[list[str]], expected: list[str]) -> None:
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
        ["CPython"],
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
        [],
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
        (["CPython"], "2.7"),
        ([], None),
    ],
)
def test_interpreter_constraints_minimum_python_version(
    constraints: list[str], expected: str
) -> None:
    universe = ["2.7", "3.5", "3.6", "3.7", "3.8", "3.9", "3.10"]
    ics = InterpreterConstraints(constraints)
    assert ics.minimum_python_version(universe) == expected
    assert ics.minimum_python_version(reversed(universe)) == expected
    assert ics.minimum_python_version(sorted(universe)) == expected


@pytest.mark.parametrize(
    "constraints,expected",
    [
        (["CPython>=2.7"], "CPython==2.7.*"),
        (["CPython>=2.7,!=2.7.2"], "CPython==2.7.*,!=2.7.2"),
        (["CPython>=3.7"], "CPython==3.7.*"),
        (["CPython>=3.8.3,!=3.8.5,!=3.9.1"], "CPython==3.8.*,!=3.8.0,!=3.8.1,!=3.8.2,!=3.8.5"),
        (["CPython==3.5.*", "CPython>=3.6"], "CPython==3.5.*"),
        (["CPython==3.7.*", "PyPy==3.6.*"], "PyPy==3.6.*"),
        (["CPython"], "CPython==2.7.*"),
        (["CPython==3.7.*,<3.6"], None),
        ([], None),
    ],
)
def test_snap_to_minimum(constraints, expected) -> None:
    universe = ["2.7", "3.5", "3.6", "3.7", "3.8", "3.9", "3.10"]
    ics = InterpreterConstraints(constraints)
    snapped = ics.snap_to_minimum(universe)
    if expected is None:
        assert snapped is None
    else:
        assert snapped == InterpreterConstraints([expected])


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
    ics = InterpreterConstraints(constraints)
    universe = ("2.7", "3.6", "3.7", "3.8", "3.9", "3.10", "3.11")
    assert ics.requires_python38_or_newer(universe) is True
    assert ics.requires_python38_or_newer(reversed(universe)) is True
    assert ics.requires_python38_or_newer(sorted(universe)) is True


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
        ["CPython"],
        [],
    ],
)
def test_interpreter_constraints_do_not_require_python38(constraints):
    ics = InterpreterConstraints(constraints)
    universe = ("2.7", "3.6", "3.7", "3.8", "3.9", "3.10", "3.11")
    assert ics.requires_python38_or_newer(universe) is False
    assert ics.requires_python38_or_newer(reversed(universe)) is False
    assert ics.requires_python38_or_newer(sorted(universe)) is False


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


_SKIPPED_PY3 = "!=3.0.*,!=3.1.*,!=3.2.*,!=3.3.*,!=3.4.*"


@pytest.mark.parametrize(
    "constraints,expected",
    (
        (["==2.7.*"], "==2.7.*"),
        (["==2.7.*", ">=3.6,!=3.6.1"], "!=3.6.1,>=3.6 || ==2.7.*"),
        ([], "*"),
        # If any of the constraints are unconstrained (e.g. `CPython`), use a wildcard.
        (["==2.7", ""], "*"),
    ),
)
def test_to_poetry_constraint(constraints: list[str], expected: str) -> None:
    assert InterpreterConstraints(constraints).to_poetry_constraint() == expected


_ALL_PATCHES = list(range(_PATCH_VERSION_UPPER_BOUND + 1))


def patches(
    major: int, minor: int, unqualified_patches: Iterable[int]
) -> list[tuple[int, int, int]]:
    return [(major, minor, patch) for patch in unqualified_patches]


@pytest.mark.parametrize(
    "constraints,expected",
    (
        (["==2.7.15"], [(2, 7, 15)]),
        (["==2.7.*"], patches(2, 7, _ALL_PATCHES)),
        (["==3.6.15", "==3.7.15"], [(3, 6, 15), (3, 7, 15)]),
        (["==3.6.*", "==3.7.*"], patches(3, 6, _ALL_PATCHES) + patches(3, 7, _ALL_PATCHES)),
        (
            ["==2.7.1", ">=3.6.15"],
            (
                [(2, 7, 1)]
                + patches(3, 6, range(15, _PATCH_VERSION_UPPER_BOUND + 1))
                + patches(3, 7, _ALL_PATCHES)
                + patches(3, 8, _ALL_PATCHES)
                + patches(3, 9, _ALL_PATCHES)
            ),
        ),
        ([], []),
    ),
)
def test_enumerate_python_versions(
    constraints: list[str], expected: list[tuple[int, int, int]]
) -> None:
    assert InterpreterConstraints(constraints).enumerate_python_versions(
        ["2.7", "3.5", "3.6", "3.7", "3.8", "3.9"]
    ) == FrozenOrderedSet(expected)


def test_enumerate_python_versions_none_matching() -> None:
    with pytest.raises(ValueError):
        InterpreterConstraints(["==3.6.*"]).enumerate_python_versions(interpreter_universe=["2.7"])


@pytest.mark.parametrize("version", ["2.6", "2.8", "4.1", "1.0"])
def test_enumerate_python_versions_invalid_universe(version: str) -> None:
    with pytest.raises(AssertionError):
        InterpreterConstraints(["==2.7.*", "==3.5.*"]).enumerate_python_versions([version])


@pytest.mark.parametrize(
    "candidate,target,matches",
    (
        ([">=3.5,<=3.6"], [">=3.5.5"], False),  # Target ICs contain versions in the 3.6 range
        ([">=3.5,<=3.6"], [">=3.5.5,<=3.5.10"], True),
        (
            [">=3.5", "<=3.6"],
            [">=3.5.5,<=3.5.10"],
            True,
        ),  # Target ICs match each of the actual ICs individually
        (
            [">=3.5", "<=3.5.4"],
            [">=3.5.5,<=3.5.10"],
            True,
        ),  # Target ICs do not match any candidate ICs
        ([">=3.5,<=3.6"], ["==3.5.*,!=3.5.10"], True),
        (
            [">=3.5,<=3.6, !=3.5.10"],
            ["==3.5.*"],
            False,
        ),  # Excluded IC from candidate range is valid for target ICs
        ([">=3.5"], [">=3.5,<=3.6", ">= 3.8"], True),
        (
            [">=3.5,!=3.7.10"],
            [">=3.5,<=3.6", ">= 3.8"],
            True,
        ),  # Excluded version from candidate ICs is not in a range specified by target ICs
        (
            [">=3.5,<=3.6", ">= 3.8"],
            [">=3.9"],
            True,
        ),  # matches only one of the candidate specifications
        (
            ["<3.6", ">=3.6"],
            [">=3.5"],
            True,
        ),  # target matches a weirdly specified non-disjoint IC list
    ),
)
def test_contains(candidate, target, matches) -> None:
    assert (
        InterpreterConstraints(candidate).contains(
            InterpreterConstraints(target), ["2.7", "3.5", "3.6", "3.7", "3.8", "3.9", "3.10"]
        )
        == matches
    )


@pytest.mark.parametrize(
    "root_ics,ics_by_path_spec",
    (
        (["==3.5.*", None], {"root1": "==3.5.*", "inner": ">=3.5"}),
        (None, {"root1": "==3.5.*", "inner": ">=3.6"}),
        (["==3.7.*", ">=3.5"], {"root1": "==3.7.*", "inner": ">=3.6", "leaf": ">=3.5"}),
        (["==3.5.*", ">=3.5"], {"root1": "==3.5.*", "leaf": ">=3.5"}),
        (None, {"root1": "==3.5.*", "leaf": ">=3.6"}),
        ([None, "==3.5.*"], {"root2": "==3.5.*", "root3": "==3.5.*"}),
        (None, {"root2": "==3.5.*", "root3": "==3.6.*"}),
        (None, {"root2": "==3.5.*", "root3": ">=3.5"}),
    ),
)
def test_validate_targets(
    root_ics: list[str | None] | None, ics_by_path_spec: dict[str, str]
) -> None:
    def t(path_spec: str) -> Target:
        address = Address(path_spec)
        ics = ics_by_path_spec.get(path_spec)
        if ics is None:
            return PythonSourcesGeneratorTarget({}, address)
        else:
            return PythonSourceTarget(
                {InterpreterConstraintsField.alias: [ics], "source": f"{path_spec}.py"}, address
            )

    expected = (
        [(InterpreterConstraints([ics]) if ics else None) for ics in root_ics] if root_ics else None
    )
    assert expected == InterpreterConstraints.compute_for_targets(
        [
            CoarsenedTarget(
                [t("root1")],
                [CoarsenedTarget([t("inner")], [CoarsenedTarget([t("leaf")], [])])],
            ),
            CoarsenedTarget([t("root2"), t("root3")], [CoarsenedTarget([t("leaf")], [])]),
        ],
        create_subsystem(
            PythonSetup,
            interpreter_constraints=[],
            interpreter_versions_universe=["3.5", "3.6", "3.7"],
        ),
    )


def test_constraints_are_correctly_sorted_at_construction() -> None:
    # #12578: This list itself is out of order, and `CPython>=3.6,<4,!=3.7.*` is specified with
    # out-of-order component requirements. This test verifies that the list is fully sorted after
    # the first call to `InterpreterConstraints()`
    inputs = ["CPython==2.7.*", "PyPy", "CPython>=3.6,<4,!=3.7.*"]
    a = InterpreterConstraints(inputs)
    a_str = [str(i) for i in a]
    b = InterpreterConstraints(a_str)
    assert a == b


@pytest.mark.parametrize(
    "constraints,expected",
    (
        (["==2.7.*"], ["2.7"]),
        ([">=3.7"], ["3.7", "3.8", "3.9", "3.10"]),
        (["==2.7", "==3.6.5"], ["2.7", "3.6"]),
    ),
)
def test_partition_into_major_minor_versions(constraints: list[str], expected: list[str]) -> None:
    assert InterpreterConstraints(constraints).partition_into_major_minor_versions(
        ["2.7", "3.6", "3.7", "3.8", "3.9", "3.10"]
    ) == tuple(expected)
