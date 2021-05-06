# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import re
from enum import Enum
from typing import Optional

from pants.core.goals.test import RuntimePackageDependenciesField
from pants.engine.addresses import Address
from pants.engine.process import BinaryPathTest
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    Dependencies,
    IntField,
    InvalidFieldException,
    Sources,
    StringField,
    Target,
)
from pants.util.enums import match


class ShellSources(Sources):
    # Normally, we would add `expected_file_extensions = ('.sh',)`, but Bash scripts don't need a
    # file extension, so we don't use this.
    uses_source_roots = False


# -----------------------------------------------------------------------------------------------
# `shunit2_tests` target
# -----------------------------------------------------------------------------------------------


class Shunit2Shell(Enum):
    sh = "sh"
    bash = "bash"
    dash = "dash"
    ksh = "ksh"
    pdksh = "pdksh"
    zsh = "zsh"

    @classmethod
    def parse_shebang(cls, shebang: bytes) -> Shunit2Shell | None:
        if not shebang:
            return None
        first_line = shebang.splitlines()[0]
        matches = re.match(rb"^#! *[/\w]*/(?P<program>\w+) *(?P<arg>\w*)", first_line)
        if not matches:
            return None
        program = matches.group("program")
        if program == b"env":
            program = matches.group("arg")
        try:
            return cls(program.decode())
        except ValueError:
            return None

    @property
    def binary_path_test(self) -> BinaryPathTest | None:
        arg = match(  # type: ignore[misc]
            self,
            {
                self.sh: None,
                self.bash: "--version",
                self.dash: None,
                self.ksh: "--version",
                self.pdksh: None,
                self.zsh: "--version",
            },
        )
        if not arg:
            return None
        return BinaryPathTest((arg,))


class Shunit2TestsDependencies(Dependencies):
    supports_transitive_excludes = True


class Shunit2TestsSources(ShellSources):
    default = ("*_test.sh", "test_*.sh", "tests.sh")


class Shunit2TestsTimeout(IntField):
    alias = "timeout"
    help = (
        "A timeout (in seconds) used by each test file belonging to this target. "
        "If unset, the test will never time out."
    )

    @classmethod
    def compute_value(cls, raw_value: Optional[int], address: Address) -> Optional[int]:
        value = super().compute_value(raw_value, address)
        if value is not None and value < 1:
            raise InvalidFieldException(
                f"The value for the `timeout` field in target {address} must be > 0, but was "
                f"{value}."
            )
        return value


class Shunit2ShellField(StringField):
    alias = "shell"
    valid_choices = Shunit2Shell
    help = "Which shell to run the tests with. If unspecified, Pants will look for a shebang line."


class Shunit2Tests(Target):
    alias = "shunit2_tests"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        Shunit2TestsDependencies,
        Shunit2TestsSources,
        Shunit2TestsTimeout,
        Shunit2ShellField,
        RuntimePackageDependenciesField,
    )
    help = (
        "Tests of Bourne-based shell scripts using the shUnit2 test framework.\n\n"
        "To use, add tests to your file per https://github.com/kward/shunit2/. Specify the shell "
        f"to run with by either setting the field `{Shunit2ShellField.alias}` or including a "
        f"shebang. To test the same file with multiple shells, create multiple `shunit2_tests` "
        f"targets, one for each shell.\n\n"
        f"Pants will automatically download the `shunit2` bash script and add "
        f"`source ./shunit2` to your test for you. If you already have `source ./shunit2`, "
        f"Pants will overwrite it to use the correct relative path."
    )


# -----------------------------------------------------------------------------------------------
# `shell_library` target
# -----------------------------------------------------------------------------------------------


class ShellLibrarySources(ShellSources):
    default = ("*.sh",) + tuple(f"!{pat}" for pat in Shunit2TestsSources.default)


class ShellLibrary(Target):
    alias = "shell_library"
    core_fields = (*COMMON_TARGET_FIELDS, Dependencies, ShellLibrarySources)
    help = "Bourne-based shell scripts, e.g. Bash scripts."
