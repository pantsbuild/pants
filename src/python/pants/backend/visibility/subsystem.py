# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from pants.option.option_types import BoolOption, SkipOption
from pants.option.subsystem import Subsystem
from pants.util.strutil import softwrap


class VisibilitySubsystem(Subsystem):
    name = "Visibility Rules"
    options_scope = "visibility"
    help = "Options for the visibility rules implementation of the dependency rules API."

    skip = SkipOption("lint")

    enforce = BoolOption(
        default=True,
        help=softwrap(
            """
            Visibility rules are enforced whenever dependencies are calculated unless `enforce` is
            set to false.
            """
        ),
    )
