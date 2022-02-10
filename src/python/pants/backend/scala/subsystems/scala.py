# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.option.option_types import StrOption
from pants.option.subsystem import Subsystem

DEFAULT_SCALA_VERSION = "2.13.6"


class ScalaSubsystem(Subsystem):
    options_scope = "scala"
    help = "Scala programming language"

    version = StrOption(
        "--version", default=DEFAULT_SCALA_VERSION, help="The version of Scala to use"
    )
