# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.option.option_types import SkipOption, ArgsListOption
from pants.option.subsystem import Subsystem
from pants.util.ordered_set import FrozenOrderedSet

# TODO we want to provide possibility for customising input for example using --config
SUPPORTED_RUSTFMT_ARGS = FrozenOrderedSet(())
SUPPORTED_RUSTFMT_ARGS_AS_HELP = ", ".join([f"`{arg}`" for arg in SUPPORTED_RUSTFMT_ARGS])


class RustfmtSubsystem(Subsystem):
    options_scope = "rustfmt"

    name = "rustfmt"
    help = "Rustfmt-specific options."
    skip = SkipOption("fmt", "lint")

    args = ArgsListOption(
        example="",
        extra_help=f"Only the following style related options are supported: {SUPPORTED_RUSTFMT_ARGS_AS_HELP}.",
    )
