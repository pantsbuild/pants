# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.option.option_types import BoolOption
from pants.option.subsystem import Subsystem
from pants.util.strutil import softwrap


class TomlSetup(Subsystem):
    options_scope = "toml-setup"
    help = "Options for Pants's TOML support."

    tailor = BoolOption(
        default=True,
        help=softwrap(
            """
            If true, add `toml_sources` targets with the `tailor` goal.
            """
        ),
        advanced=True,
    )
