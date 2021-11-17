# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from typing import cast

from pants.option.subsystem import Subsystem


class ScalaInferSubsystem(Subsystem):
    options_scope = "scala-infer"
    help = "Options controlling which dependencies will be inferred for Scala targets."

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--imports",
            default=True,
            type=bool,
            help="Infer a target's dependencies by parsing import statements from sources.",
        )
        register(
            "--consumed-types",
            default=True,
            type=bool,
            help=("Infer a target's dependencies by parsing consumed types from sources."),
        )

    @property
    def imports(self) -> bool:
        return cast(bool, self.options.imports)

    @property
    def consumed_types(self) -> bool:
        return cast(bool, self.options.consumed_types)
