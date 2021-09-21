# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.option.custom_types import shell_str
from pants.option.subsystem import Subsystem


class JUnit(Subsystem):
    options_scope = "junit"
    help = "The JUnit test framework (https://junit.org)"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)

        register(
            "--args",
            type=list,
            member_type=shell_str,
            passthrough=True,
            help="Arguments to pass directly to JUnit, e.g. `--disable-ansi-colors`",
        )
