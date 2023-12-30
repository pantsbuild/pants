# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from dataclasses import dataclass
from typing import Any

from pants.backend.adhoc import code_quality_tool, run_system_binary
from pants.backend.adhoc.code_quality_tool import CodeQualityToolRuleBuilder, CodeQualityToolTarget
from pants.backend.adhoc.target_types import SystemBinaryTarget
from pants.base.exceptions import BackendConfigurationError
from pants.core.util_rules import adhoc_process_support


@dataclass
class CodeQualityToolBackend:
    rule_builder: CodeQualityToolRuleBuilder

    def rules(self):
        return [
            *run_system_binary.rules(),
            *adhoc_process_support.rules(),
            *code_quality_tool.base_rules(),
            *self.rule_builder.rules(),
        ]

    def target_types(self):
        return [
            SystemBinaryTarget,
            CodeQualityToolTarget,
        ]


def _validate(kwargs: dict[str, Any]) -> dict[str, Any]:
    required = ["goal", "target", "name"]
    missing = [k for k in required if k not in kwargs]
    if missing:
        raise BackendConfigurationError(
            f"Missing required keys {missing} for backend template {__name__}."
            f" Supplied {dict(kwargs)}."
        )

    return {k: str(v) for k, v in kwargs.items()}


def generate(backend_package_alias: str, kwargs: dict[str, Any]):
    kwargs = _validate(kwargs)

    rule_builder = CodeQualityToolRuleBuilder(
        goal=kwargs["goal"],
        target=kwargs["target"],
        name=kwargs["name"],
        scope=backend_package_alias,
    )

    return CodeQualityToolBackend(rule_builder)
