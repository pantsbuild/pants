# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.option.custom_types import file_option
from pants.subsystem.subsystem import Subsystem


class Checkstyle(Subsystem):

    options_scope = "checkstyle"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--config",
            type=file_option,
            default=None,
            fingerprint=True,
            help="Path to Checkstyle config file.",
        )
        register(
            "--skip",
            type=bool,
            default=False,
            help="Don't use Checkstyle when running `./pants lint`.",
        )
