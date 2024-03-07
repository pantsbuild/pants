# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.adhoc import adhoc_tool, code_quality_tool, run_system_binary
from pants.backend.adhoc.code_quality_tool import CodeQualityToolTarget
from pants.backend.adhoc.target_types import AdhocToolTarget, SystemBinaryTarget


def target_types():
    return [
        AdhocToolTarget,
        SystemBinaryTarget,
        CodeQualityToolTarget,
    ]


def rules():
    return [
        *adhoc_tool.rules(),
        *run_system_binary.rules(),
        *code_quality_tool.base_rules(),
    ]
