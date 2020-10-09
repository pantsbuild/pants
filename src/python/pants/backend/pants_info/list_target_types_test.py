# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
from enum import Enum
from textwrap import dedent
from typing import Optional, cast

from pants.backend.pants_info.list_target_types import TargetTypesSubsystem, list_target_types
from pants.core.util_rules.pants_bin import PantsBin
from pants.engine.target import IntField, RegisteredTargetTypes, StringField, Target, TriBoolField
from pants.engine.unions import UnionMembership
from pants.testutil.option_util import create_goal_subsystem
from pants.testutil.rule_runner import MockConsole, run_rule_with_mocks


# Note no docstring.
class FortranVersion(StringField):
    alias = "fortran_version"


class GenericTimeout(IntField):
    """The number of seconds to run before timing out."""

    alias = "timeout"


# Note no docstring, but GenericTimeout has it, so we should end up using that.
class FortranTimeout(GenericTimeout):
    pass


class FortranLibrary(Target):
    """A library of Fortran code."""

    alias = "fortran_library"
    core_fields = (FortranVersion,)


# Note multiline docstring.
class FortranTests(Target):
    """Tests for Fortran code.

    This assumes that you use the FRUIT test framework.
    """

    alias = "fortran_tests"
    core_fields = (FortranVersion, FortranTimeout)


class ArchiveFormat(Enum):
    TGZ = ".tgz"
    TAR = ".tar"


class ArchiveFormatField(StringField):
    alias = "archive_format"
    valid_choices = ArchiveFormat
    default = ArchiveFormat.TGZ.value


class ErrorBehavior(StringField):
    alias = "error_behavior"
    valid_choices = ("ignore", "warn", "error")
    required = True


# Note no docstring.
class FortranBinary(Target):
    alias = "fortran_binary"
    core_fields = (FortranVersion, ArchiveFormatField, ErrorBehavior)


def run_goal(
    *,
    union_membership: Optional[UnionMembership] = None,
    details_target: Optional[str] = None,
    all: bool = False
) -> str:
    console = MockConsole(use_colors=False)
    run_rule_with_mocks(
        list_target_types,
        rule_args=[
            RegisteredTargetTypes.create([FortranBinary, FortranLibrary, FortranTests]),
            union_membership or UnionMembership({}),
            create_goal_subsystem(
                TargetTypesSubsystem, sep="\\n", output_file=None, details=details_target, all=all
            ),
            console,
            PantsBin(name="./BNF"),
        ],
    )
    return cast(str, console.stdout.getvalue())


def test_list_all_abbreviated() -> None:
    stdout = run_goal()
    assert stdout == dedent(
        """\

        Target types
        ------------

        Use `./BNF target-types --details=$target_type` to get detailed information for
        a particular target type.


        fortran_binary   <no description>

        fortran_library  A library of Fortran code.

        fortran_tests    Tests for Fortran code.
        """
    )


def test_list_all_json() -> None:
    stdout = run_goal(all=True)
    fortran_version = {
        "default": None,
        "description": None,
        "required": False,
        "type_hint": "str | None",
    }
    assert json.loads(stdout) == {
        "fortran_binary": {
            "description": None,
            "fields": {
                "archive_format": {
                    "default": "'.tgz'",
                    "description": None,
                    "required": False,
                    "type_hint": "'.tar' | '.tgz' | None",
                },
                "error_behavior": {
                    "default": None,
                    "description": None,
                    "required": True,
                    "type_hint": "'error' | 'ignore' | 'warn'",
                },
                "fortran_version": fortran_version,
            },
        },
        "fortran_library": {
            "description": "A library of Fortran code.",
            "fields": {"fortran_version": fortran_version},
        },
        "fortran_tests": {
            "description": (
                "Tests for Fortran code.\n\nThis assumes that you use the FRUIT test framework."
            ),
            "fields": {
                "fortran_version": fortran_version,
                "timeout": {
                    "default": None,
                    "description": "The number of seconds to run before timing out.",
                    "required": False,
                    "type_hint": "int | None",
                },
            },
        },
    }


def test_list_single() -> None:
    class CustomField(TriBoolField):
        """My custom field!

        Use this field to...
        """

        alias = "custom_field"
        required = True

    tests_target_stdout = run_goal(
        union_membership=UnionMembership.from_rules(
            [FortranTests.register_plugin_field(CustomField)]
        ),
        details_target=FortranTests.alias,
    )
    assert tests_target_stdout == dedent(
        """\

        fortran_tests
        -------------

        Tests for Fortran code.

        This assumes that you use the FRUIT test framework.

        Valid fields:

            custom_field
                type: bool, required
                My custom field! Use this field to...

            fortran_version
                type: str | None, default: None

            timeout
                type: int | None, default: None
                The number of seconds to run before timing out.
        """
    )

    binary_target_stdout = run_goal(details_target=FortranBinary.alias)
    assert binary_target_stdout == dedent(
        """\

        fortran_binary
        --------------

        Valid fields:

            archive_format
                type: '.tar' | '.tgz' | None, default: '.tgz'

            error_behavior
                type: 'error' | 'ignore' | 'warn', required

            fortran_version
                type: str | None, default: None
        """
    )
