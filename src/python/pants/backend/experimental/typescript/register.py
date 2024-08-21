# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from typing import Iterable, Union

from pants.backend.typescript.dependency_inference import rules as dependency_inference_rules
from pants.backend.typescript.goals import tailor
from pants.backend.typescript.target_types import (
    TypeScriptSourcesGeneratorTarget,
    TypeScriptSourceTarget,
    TypeScriptTestsGeneratorTarget,
    TypeScriptTestTarget,
)
from pants.engine.rules import Rule
from pants.engine.target import Target
from pants.engine.unions import UnionRule


def target_types() -> Iterable[type[Target]]:
    return (
        TypeScriptSourceTarget,
        TypeScriptSourcesGeneratorTarget,
        TypeScriptTestTarget,
        TypeScriptTestsGeneratorTarget,
    )


def rules() -> Iterable[Union[Rule, UnionRule]]:
    return (
        *dependency_inference_rules.rules(),
        *tailor.rules(),
    )
