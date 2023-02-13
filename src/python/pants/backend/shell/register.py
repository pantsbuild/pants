# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.shell import dependency_inference, shunit2_test_runner
from pants.backend.shell.goals import tailor, test
from pants.backend.shell.subsystems import shunit2
from pants.backend.shell.target_types import (
    ShellCommandRunTarget,
    ShellCommandTarget,
    ShellCommandTestTarget,
    ShellSourcesGeneratorTarget,
    ShellSourceTarget,
    Shunit2TestsGeneratorTarget,
    Shunit2TestTarget,
)
from pants.backend.shell.target_types import rules as target_types_rules
from pants.backend.shell.util_rules import shell_command


def target_types():
    return [
        ShellCommandTarget,
        ShellCommandRunTarget,
        ShellCommandTestTarget,
        ShellSourcesGeneratorTarget,
        Shunit2TestsGeneratorTarget,
        ShellSourceTarget,
        Shunit2TestTarget,
    ]


def rules():
    return [
        *dependency_inference.rules(),
        *shell_command.rules(),
        *shunit2.rules(),
        *shunit2_test_runner.rules(),
        *tailor.rules(),
        *target_types_rules(),
        *test.rules(),
    ]
