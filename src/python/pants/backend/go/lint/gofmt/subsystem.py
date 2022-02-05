# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.option.option_types import BoolOption
from pants.option.subsystem import Subsystem


class GofmtSubsystem(Subsystem):
    options_scope = "gofmt"
    help = "Gofmt-specific options."

    skip = BoolOption(
        "--skip",
        default=False,
        help=("Don't use gofmt when running `./pants fmt` and `./pants lint`."),
    )
