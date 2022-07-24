# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.target_types import (
    PythonSourcesGeneratorTarget,
    PythonSourceTarget,
    PythonTestsGeneratorTarget,
    PythonTestTarget,
    PythonTestUtilsGeneratorTarget,
)
from pants.engine.target import BoolField


class SkipPipAuditField(BoolField):
    alias = "skip_pip_audit"
    default = False
    help = "If true, don't run pip-audit on this target's code."


def rules():
    return [
        PythonSourcesGeneratorTarget.register_plugin_field(SkipPipAuditField),
        PythonSourceTarget.register_plugin_field(SkipPipAuditField),
        PythonTestsGeneratorTarget.register_plugin_field(SkipPipAuditField),
        PythonTestTarget.register_plugin_field(SkipPipAuditField),
        PythonTestUtilsGeneratorTarget.register_plugin_field(SkipPipAuditField),
    ]
