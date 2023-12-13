# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.backend.adhoc.code_quality_tool import CodeQualityToolRuleBuilder


def rules(backend_package_alias: str, goal: str, target: str, name: str):
    cfg = CodeQualityToolRuleBuilder(
        goal=goal,
        target=target,
        name=name,
        scope=backend_package_alias,
    )
    return cfg.rules()