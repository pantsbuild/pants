# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from typing import Iterable

from pants.backend.adhoc import run_system_binary
from pants.backend.adhoc.target_types import SystemBinaryTarget
from pants.backend.experimental.code_quality_tool.lib import (
    CodeQualityToolRuleBuilder,
    CodeQualityToolTarget,
    base_rules,
)
from pants.engine.rules import Rule
from pants.engine.target import Target


def target_types() -> Iterable[type[Target]]:
    return [
        SystemBinaryTarget,
        CodeQualityToolTarget,
    ]


def rules(*tools: CodeQualityToolRuleBuilder) -> Iterable[Rule]:
    rules = [
        *base_rules(),
        *run_system_binary.rules(),
    ]

    for tool in tools:
        rules.extend(tool.rules())

    return rules
