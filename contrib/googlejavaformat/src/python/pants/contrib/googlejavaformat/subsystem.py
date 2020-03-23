# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.subsystem.subsystem import Subsystem


class GoogleJavaFormat(Subsystem):

    options_scope = "google-java-format"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--skip",
            type=bool,
            default=False,
            help="Don't use `google-java-format` when running `./pants fmt` and `./pants lint`.",
        )
