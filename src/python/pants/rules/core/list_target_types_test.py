# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from contextlib import contextmanager
from typing import Optional, cast
from unittest.mock import Mock

from pants.engine.rules import UnionMembership
from pants.engine.target import BoolField, RegisteredTargetTypes, Target
from pants.rules.core.list_target_types import list_target_types
from pants.testutil.engine.util import MockConsole, run_rule
from pants.util.ordered_set import OrderedSet


# TODO(#9141): replace this with a proper util to create `GoalSubsystem`s
class MockOptions:
    def __init__(self, **values):
        self.values = Mock(**values)

    @contextmanager
    def line_oriented(self, console: MockConsole):
        yield lambda msg: console.print_stdout(msg)


class HaskellLibrary(Target):
    """A library of Haskell code."""

    alias = "haskell_library"
    core_fields = ()


# Note multiline docstring.
class HaskellTests(Target):
    """Tests for Haskell code.

    This assumes that you use QuickCheck or an equivalent test runner.
    """

    alias = "haskell_tests"
    core_fields = ()


# Note no docstring.
class HaskellBinary(Target):
    alias = "haskell_binary"
    core_fields = ()


def run_goal(
    *, union_membership: Optional[UnionMembership] = None, details_target: Optional[str] = None
) -> str:
    console = MockConsole(use_colors=False)
    run_rule(
        list_target_types,
        rule_args=[
            RegisteredTargetTypes.create([HaskellBinary, HaskellLibrary, HaskellTests]),
            union_membership or UnionMembership({}),
            MockOptions(details=details_target),
            console,
        ],
    )
    return cast(str, console.stdout.getvalue())


def test_list_all() -> None:
    stdout = run_goal()
    assert len(stdout.strip()) == 3

    assert HaskellLibrary.alias in stdout
    assert "A library of Haskell code." in stdout

    assert HaskellTests.alias in stdout
    assert "Tests for Haskell code." in stdout
    assert "This assumes that you use QuickCheck or an equivalent test runner." not in stdout

    assert HaskellBinary.alias in stdout
    assert "<no description>" in stdout


def test_list_single_target_type() -> None:
    class CustomField(BoolField):
        """My custom field!"""

        default = True
        alias = "custom_field"

    stdout = run_goal(
        union_membership=UnionMembership({HaskellTests.PluginField: OrderedSet([CustomField])}),
        details_target=HaskellTests.alias,
    )

    assert "Tests for Haskell code." in stdout
    # TODO: we really want to be able to assert this.
    # assert (
    #     "Tests for Haskell code. This assumes that you use QuickCheck or an equivalent test "
    #     "runner."
    # ) in stdout
