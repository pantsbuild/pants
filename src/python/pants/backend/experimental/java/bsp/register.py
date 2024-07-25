# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.experimental.bsp.register import auxillary_goals as bsp_auxillary_goals
from pants.backend.experimental.bsp.register import rules as bsp_rules
from pants.backend.experimental.java.register import build_file_aliases as java_build_file_aliases
from pants.backend.experimental.java.register import rules as java_rules
from pants.backend.experimental.java.register import target_types as java_target_types
from pants.backend.java.bsp.rules import rules as java_bsp_rules


def auxillary_goals():
    return bsp_auxillary_goals()


def target_types():
    return java_target_types()


def rules():
    return (
        *java_rules(),
        *bsp_rules(),
        *java_bsp_rules(),
    )


def build_file_aliases():
    return java_build_file_aliases()
