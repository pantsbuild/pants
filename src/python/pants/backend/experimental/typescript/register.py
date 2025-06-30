# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from collections.abc import Iterable

from pants.backend.tsx.goals import tailor as tsx_tailor
from pants.backend.tsx.target_types import (
    TSXSourcesGeneratorTarget,
    TSXSourceTarget,
    TSXTestsGeneratorTarget,
    TSXTestTarget,
)
from pants.backend.typescript.goals import check, tailor
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
        TSXSourcesGeneratorTarget,
        TSXSourceTarget,
        TSXTestsGeneratorTarget,
        TSXTestTarget,
    )


def rules() -> Iterable[Rule | UnionRule]:
    return (
        *tailor.rules(),
        *tsx_tailor.rules(),
        *check.rules(),
    )
