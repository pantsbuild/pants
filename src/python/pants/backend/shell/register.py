# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.shell import dependency_inference, shell_command, shunit2_test_runner, tailor
from pants.backend.shell.target_types import (
    ShellCommandRunTarget,
    ShellCommandTarget,
    ShellSourcesGeneratorTarget,
    ShellSourceTarget,
    Shunit2TestsGeneratorTarget,
    Shunit2TestTarget,
)
from pants.backend.shell.target_types import rules as target_types_rules
from pants.base.deprecated import deprecated


@deprecated(
    removal_version="2.12.0.dev0",
    hint=(
        "The `experimental_run_shell_command` target has migrated to the "
        "`pants.backend.experimental.shell` backend and renamed to `run_shell_command`."
    ),
)
class ExperimentalShellCommandRunTarget(ShellCommandRunTarget):
    pass


@deprecated(
    removal_version="2.12.0.dev0",
    hint=(
        "The `experimental_shell_command` target has migrated to the "
        "`pants.backend.experimental.shell` backend and renamed to `shell_command`."
    ),
)
class ExperimentalShellCommandTarget(ShellCommandTarget):
    pass


def target_types():
    return [
        ExperimentalShellCommandRunTarget,
        ExperimentalShellCommandTarget,
        ShellSourcesGeneratorTarget,
        Shunit2TestsGeneratorTarget,
        ShellSourceTarget,
        Shunit2TestTarget,
    ]


def rules():
    return [
        *dependency_inference.rules(),
        *shell_command.rules(),
        *shunit2_test_runner.rules(),
        *tailor.rules(),
        *target_types_rules(),
    ]
