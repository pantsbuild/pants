# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.backend.cc.dependency_inference.rules import rules as dep_inf_rules
from pants.backend.cc.goals import tailor
from pants.backend.cc.target_types import CCSourcesGeneratorTarget, CCSourceTarget
from pants.backend.cc.target_types import rules as target_type_rules


def target_types():
    return [CCSourceTarget, CCSourcesGeneratorTarget]


def rules():
    return [
        *dep_inf_rules(),
        *tailor.rules(),
        *target_type_rules(),
    ]
