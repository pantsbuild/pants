# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.subsystem.subsystem import Subsystem


class PythonEval(Subsystem):

    options_scope = "python-eval"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--skip",
            type=bool,
            default=True,
            help="Don't use `python-eval` when running `./pants lint`.",
        )
