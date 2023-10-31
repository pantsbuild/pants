# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.backend.adhoc import run_system_binary
from pants.backend.adhoc.target_types import SystemBinaryTarget
from pants.core.util_rules.adhoc_process_support import rules as adhoc_process_support_rules
from pants.backend.code_quality_tool.lib import CodeQualityToolTarget, CodeQualityToolConfig, build_rules


def target_types(**kwargs):
    return [
        SystemBinaryTarget,
        CodeQualityToolTarget,
    ]


def rules(**kwargs):
    config = CodeQualityToolConfig(**kwargs)
    return [
        *build_rules(config),
        *adhoc_process_support_rules(),
        *run_system_binary.rules(),
    ]
