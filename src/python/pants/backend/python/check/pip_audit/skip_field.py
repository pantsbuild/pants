# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.backend.python.macros.pipenv_requirements import PipenvRequirementsTargetGenerator
from pants.backend.python.macros.poetry_requirements import PoetryRequirementsTargetGenerator
from pants.backend.python.macros.python_requirements import PythonRequirementsTargetGenerator
from pants.backend.python.target_types import PythonRequirementTarget
from pants.engine.target import BoolField


class SkipPipAuditField(BoolField):
    alias = "skip_pip_audit"
    default = False
    help = "If true, don't run pip-audit on this requirement."


def rules():
    return [
        PipenvRequirementsTargetGenerator.register_plugin_field(SkipPipAuditField),
        PoetryRequirementsTargetGenerator.register_plugin_field(SkipPipAuditField),
        PythonRequirementsTargetGenerator.register_plugin_field(SkipPipAuditField),
        PythonRequirementTarget.register_plugin_field(SkipPipAuditField),
    ]
