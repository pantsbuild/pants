# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.backend.python.util_rules.pex import rules as pex_rules
from pants.backend.terraform import dependency_inference, style, tailor, target_gen, tool
from pants.backend.terraform.goals import check
from pants.backend.terraform.lint import fmt
from pants.backend.terraform.lint.tffmt.tffmt import rules as tffmt_rules
from pants.backend.terraform.target_types import (
    TerraformModulesGeneratorTarget,
    TerraformModuleTarget,
)
from pants.backend.terraform.target_types import rules as target_types_rules
from pants.engine.rules import collect_rules


def target_types():
    return [TerraformModuleTarget, TerraformModulesGeneratorTarget]


def rules():
    return [
        *collect_rules(),
        *check.rules(),
        *dependency_inference.rules(),
        *tailor.rules(),
        *target_gen.rules(),
        *target_types_rules(),
        *tool.rules(),
        *fmt.rules(),
        *style.rules(),
        *pex_rules(),
        *tffmt_rules(),
    ]
