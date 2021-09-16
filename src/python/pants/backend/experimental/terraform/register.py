# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.backend.terraform import tailor, target_gen, target_types, tool
from pants.backend.terraform.lint import fmt
from pants.backend.terraform.target_types import TerraformModule, TerraformModules
from pants.engine.rules import collect_rules


def target_types():
    return [TerraformModule, TerraformModules]


def rules():
    return [
        *collect_rules(),
        *tailor.rules(),
        *target_gen.rules(),
        *target_types.rules(),
        *tool.rules(),
        *fmt.rules(),
    ]
