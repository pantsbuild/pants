# Copyright 2021 Pants project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.shell import tailor
from pants.backend.shell.target_types import ShellLibrary, Shunit2Tests


def target_types():
    return [ShellLibrary, Shunit2Tests]


def rules():
    return [*tailor.rules()]
