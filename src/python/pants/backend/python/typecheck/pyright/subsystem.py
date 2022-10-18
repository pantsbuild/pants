# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.option.option_types import ArgsListOption, SkipOption
from pants.option.subsystem import Subsystem
from pants.util.strutil import softwrap


class Pyright(Subsystem):
    options_scope = "pyright"
    name = "Pyright"
    help = softwrap(
        """
        The Pyright utility for typechecking Python code
        (https://github.com/microsoft/pyright).
        """
    )

    default_version = "pyright@1.1.274"

    skip = SkipOption("check")
    args = ArgsListOption(example="--version")
