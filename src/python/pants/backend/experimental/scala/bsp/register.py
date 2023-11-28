# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.backend.experimental.bsp.register import builtin_goals as bsp_builtin_goals
from pants.backend.experimental.bsp.register import rules as bsp_rules
from pants.backend.experimental.scala.register import build_file_aliases as scala_build_file_aliases
from pants.backend.experimental.scala.register import rules as scala_rules
from pants.backend.experimental.scala.register import target_types as scala_target_types
from pants.backend.scala.bsp.rules import rules as scala_bsp_rules


def builtin_goals():
    return bsp_builtin_goals()


def target_types():
    return scala_target_types()


def rules():
    return (
        *scala_rules(),
        *bsp_rules(),
        *scala_bsp_rules(),
    )


def build_file_aliases():
    return scala_build_file_aliases()
