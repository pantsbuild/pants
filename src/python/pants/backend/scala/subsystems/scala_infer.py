# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.option.option_types import BoolOption
from pants.option.subsystem import Subsystem


class ScalaInferSubsystem(Subsystem):
    options_scope = "scala-infer"
    help = "Options controlling which dependencies will be inferred for Scala targets."

    imports = BoolOption(
        "--imports",
        default=True,
        help="Infer a target's dependencies by parsing import statements from sources.",
    )
    consumed_types = BoolOption(
        "--consumed-types",
        default=True,
        help="Infer a target's dependencies by parsing consumed types from sources.",
    )
