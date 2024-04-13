# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.option.option_types import SkipOption
from pants.option.subsystem import Subsystem


class ShellTestSubsystem(Subsystem):
    options_scope = "shell-test"
    name = "Test with shell scripts"
    help = "Options for Pants' Shell test support."

    skip = SkipOption("test")
