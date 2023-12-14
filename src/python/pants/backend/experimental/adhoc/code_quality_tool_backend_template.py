# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from typing import Any

from pants.backend.adhoc.code_quality_tool import CodeQualityToolRuleBuilder


def generate(backend_package_alias: str, kwargs: dict[str, Any]):
    return CodeQualityToolRuleBuilder(
        goal=kwargs['goal'],
        target=kwargs['target'],
        name=kwargs['name'],
        scope=backend_package_alias,
    )
