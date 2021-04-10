# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.shell import shunit2_test_runner, tailor
from pants.backend.shell.target_types import ShellLibrary, Shunit2Tests


def target_types():
    return [ShellLibrary, Shunit2Tests]


def rules():
    return [*tailor.rules(), *shunit2_test_runner.rules()]
