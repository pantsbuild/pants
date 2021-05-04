# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.backend.terraform import fmt, tailor
from pants.backend.terraform import target_types as target_types_module
from pants.backend.terraform import tffmt, tool, validate
from pants.backend.terraform.target_types import TerraformModule
from pants.engine.rules import collect_rules


def target_types():
    return [TerraformModule]


def rules():
    return [
        *collect_rules(),
        *tailor.rules(),
        *target_types_module.rules(),
        *tool.rules(),
        *tffmt.rules(),
        *fmt.rules(),
        *validate.rules(),
    ]
