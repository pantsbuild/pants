# Copyright 2021 Pants project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import Optional

from pants.engine.addresses import Address
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    Dependencies,
    IntField,
    InvalidFieldException,
    Sources,
    Target,
)


class ShellSources(Sources):
    # Normally, we would add `expected_file_extensions = ('.sh',)`, but Bash scripts don't need a
    # file extension, so we don't use this.
    uses_source_roots = False


# -----------------------------------------------------------------------------------------------
# `shunit2_tests` target
# -----------------------------------------------------------------------------------------------


class Shunit2TestsSources(ShellSources):
    default = ("*_test.sh", "test_*.sh", "tests.sh")


class Shunit2TestsTimeout(IntField):
    alias = "timeout"
    help = (
        "A timeout (in seconds) used by each test file belonging to this target.\n\n"
        "If unset, the test will never time out."
    )

    @classmethod
    def compute_value(cls, raw_value: Optional[int], *, address: Address) -> Optional[int]:
        value = super().compute_value(raw_value, address=address)
        if value is not None and value < 1:
            raise InvalidFieldException(
                f"The value for the `timeout` field in target {address} must be > 0, but was "
                f"{value}."
            )
        return value


class Shunit2Tests(Target):
    alias = "shunit2_tests"
    core_fields = (*COMMON_TARGET_FIELDS, Dependencies, Shunit2TestsSources, Shunit2TestsTimeout)
    help = "Tests of Bourne-based shell scripts using the shUnit2 test framework."


# -----------------------------------------------------------------------------------------------
# `shell_library` target
# -----------------------------------------------------------------------------------------------


class ShellLibrarySources(ShellSources):
    default = ("*.sh",) + tuple(f"!{pat}" for pat in Shunit2TestsSources.default)


class ShellLibrary(Target):
    alias = "shell_library"
    core_fields = (*COMMON_TARGET_FIELDS, Dependencies, ShellLibrarySources)
    help = "Bourne-based shell scripts, e.g. Bash scripts."
