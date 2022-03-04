# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.option.option_types import SkipOption
from pants.option.subsystem import Subsystem


class GofmtSubsystem(Subsystem):
    options_scope = "gofmt"
    name = "gofmt"
    help = "Gofmt-specific options."

    skip = SkipOption("fmt", "lint")
