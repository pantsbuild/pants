# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.option.option_types import SkipOption
from pants.option.subsystem import Subsystem


class RustfmtSubsystem(Subsystem):
    options_scope = "rustfmt"

    name = "rustfmt"
    help = "Rustfmt-specific options."
    skip = SkipOption("fmt", "lint")
