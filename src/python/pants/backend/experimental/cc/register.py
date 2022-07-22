# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.cc.dependency_inference.rules import rules as dep_inf_rules
from pants.backend.cc.goals import check, tailor
from pants.backend.cc.subsystems import toolchain
from pants.backend.cc.target_types import CCSourcesGeneratorTarget, CCSourceTarget
from pants.backend.cc.target_types import rules as target_type_rules
from pants.backend.cc.util_rules import compile


def target_types():
    return [CCSourceTarget, CCSourcesGeneratorTarget]


def rules():
    return [
        *check.rules(),
        *compile.rules(),
        *dep_inf_rules(),
        *tailor.rules(),
        *toolchain.rules(),
        *target_type_rules(),
    ]
