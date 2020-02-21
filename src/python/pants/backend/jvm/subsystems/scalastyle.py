# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.option.custom_types import file_option
from pants.subsystem.subsystem import Subsystem


class Scalastyle(Subsystem):

    options_scope = "scalastyle"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--config",
            type=file_option,
            default=None,
            fingerprint=True,
            help="Path to `scalastyle_config.xml` or alternative an Scalastyle config file.",
        )
        register(
            "--skip",
            type=bool,
            default=False,
            help="Don't use Scalastyle when running `./pants lint`.",
        )
