# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.option.subsystem import Subsystem


class GofmtSubsystem(Subsystem):
    options_scope = "gofmt"
    help = "Gofmt-specific options."

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--skip",
            type=bool,
            default=False,
            help=(
                f"Don't use gofmt when running `{register.bootstrap.pants_bin_name} fmt` and "
                f"`{register.bootstrap.pants_bin_name} lint`."
            ),
        )
