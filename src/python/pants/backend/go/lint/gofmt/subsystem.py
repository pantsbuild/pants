# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.option.option_types import ArgsListOption, SkipOption
from pants.option.subsystem import Subsystem
from pants.util.ordered_set import FrozenOrderedSet

SUPPORTED_GOFMT_ARGS = FrozenOrderedSet(("-e", "-r", "-s"))
SUPPORTED_GOFMT_ARGS_AS_HELP = ", ".join([f"`{arg}`" for arg in SUPPORTED_GOFMT_ARGS])


class GofmtSubsystem(Subsystem):
    options_scope = "gofmt"
    name = "gofmt"
    help = "Gofmt-specific options."

    skip = SkipOption("fmt", "lint")
    args = ArgsListOption(
        example="-s -e",
        extra_help=f"Only the following style related options are supported: {SUPPORTED_GOFMT_ARGS_AS_HELP}.",
    )
