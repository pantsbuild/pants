# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.goals import lockfile as python_lockfile
from pants.backend.terraform import dependencies, dependency_inference, tool
from pants.backend.terraform.goals import check, deploy
from pants.backend.terraform.goals import lockfiles as terraform_lockfile
from pants.backend.terraform.goals import tailor
from pants.backend.terraform.lint.tffmt.tffmt import rules as tffmt_rules
from pants.backend.terraform.target_types import TerraformDeploymentTarget, TerraformModuleTarget
from pants.backend.terraform.target_types import rules as target_types_rules
from pants.engine.rules import collect_rules


def target_types():
    return [TerraformModuleTarget, TerraformDeploymentTarget]


def rules():
    return [
        *collect_rules(),
        *dependencies.rules(),
        *check.rules(),
        *dependency_inference.rules(),
        *tailor.rules(),
        *target_types_rules(),
        *tool.rules(),
        *tffmt_rules(),
        *deploy.rules(),
        *terraform_lockfile.rules(),
        *python_lockfile.rules(),
    ]
