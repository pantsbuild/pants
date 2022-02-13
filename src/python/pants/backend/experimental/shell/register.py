# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.shell import shell_command
from pants.backend.shell.target_types import ShellCommandRunTarget, ShellCommandTarget


def target_types():
    return [
        ShellCommandTarget,
        ShellCommandRunTarget,
    ]


def rules():
    return [
        *shell_command.rules(),
    ]
