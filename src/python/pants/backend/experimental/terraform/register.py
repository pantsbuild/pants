# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.backend.python.util_rules.pex import rules as pex_rules
from pants.backend.terraform import dependency_inference, tailor, target_gen, tool, goals
from pants.backend.terraform.lint import fmt
from pants.backend.terraform.lint.tffmt.tffmt import rules as tffmt_rules
from pants.backend.terraform.lint.validate.validate import rules as validate_rules
from pants.backend.terraform.target_types import TerraformModule, TerraformModules
from pants.backend.terraform.target_types import rules as target_types_rules
from pants.engine.rules import collect_rules


def target_types():
    return [TerraformModule, TerraformModules]


def rules():
    return [
        *collect_rules(),
        *dependency_inference.rules(),
        *goals.rules(),
        *tailor.rules(),
        *target_gen.rules(),
        *target_types_rules(),
        *tool.rules(),
        *fmt.rules(),
        *pex_rules(),
        *tffmt_rules(),
        *validate_rules(),
    ]
