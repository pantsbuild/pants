# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from contextlib import contextmanager
from textwrap import dedent
from typing import Optional, cast
from unittest.mock import Mock

from pants.engine.rules import UnionMembership
from pants.engine.target import BoolField, RegisteredTargetTypes, StringField, Target
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


# Note no docstring.
class GhcVersion(StringField):
    alias = "ghc_version"


class HaskellLibrary(Target):
    """A library of Haskell code."""

    alias = "haskell_library"
    core_fields = (GhcVersion,)


# Note multiline docstring.
class HaskellTests(Target):
    """Tests for Haskell code.

    This assumes that you use QuickCheck or an equivalent test runner.
    """

    alias = "haskell_tests"
    core_fields = (GhcVersion,)


# Note no docstring.
class HaskellBinary(Target):
    alias = "haskell_binary"
    core_fields = (GhcVersion,)


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
    assert (
        stdout
        == """\
                haskell_binary: <no description>
               haskell_library: A library of Haskell code.
                 haskell_tests: Tests for Haskell code.\n"""
    )


def test_list_single() -> None:
    class CustomField(BoolField):
        """My custom field!

        Use this field to...
        """

        default = True
        alias = "custom_field"

    tests_target_stdout = run_goal(
        union_membership=UnionMembership({HaskellTests.PluginField: OrderedSet([CustomField])}),
        details_target=HaskellTests.alias,
    )
    # TODO: render the full docstring for both the target type (preserve new lines) and for
    #  custom_field (strip new lines).
    assert tests_target_stdout == dedent(
        """\
        Tests for Haskell code.


        haskell_tests(
          custom_field = ...,           My custom field! (default: True)
          ghc_version = ...,            <no description>
        )
        """
    )

    binary_target_stdout = run_goal(details_target=HaskellBinary.alias)
    assert binary_target_stdout == dedent(
        """\
        haskell_binary(
          ghc_version = ...,            <no description>
        )
        """
    )
