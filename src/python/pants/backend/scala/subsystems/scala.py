# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from typing import cast

from pants.option.subsystem import Subsystem

DEFAULT_SCALA_VERSION = "2.13.6"


class ScalaSubsystem(Subsystem):
    options_scope = "scala"
    help = "Scala programming language"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--version", type=str, default=DEFAULT_SCALA_VERSION, help="The version of Scala to use"
        )

    @property
    def version(self) -> str:
        return cast(str, self.options.version)
