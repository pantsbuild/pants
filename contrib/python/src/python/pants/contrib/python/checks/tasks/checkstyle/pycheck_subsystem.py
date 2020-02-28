# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.subsystem.subsystem import Subsystem


class Pycheck(Subsystem):

    options_scope = "pycheck"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--skip",
            type=bool,
            default=False,
            help="Don't use the `pythonstyle` lints when running `./pants lint`. Note that you may get "
            "more granular than this by turning off specific lints, e.g. `--pycheck-newlines-skip` "
            "and `--pycheck-class-factoring-skip`. Run `./pants options | grep pycheck` to see all "
            "the possible lints to skip.",
        )
