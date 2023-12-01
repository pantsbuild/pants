# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from typing import Iterable

from pants.backend.typescript.target_types import (
    TypeScriptSourcesGeneratorTarget,
    TypeScriptSourceTarget,
    TypeScriptTestsGeneratorTarget,
    TypeScriptTestTarget,
)
from pants.engine.target import Target


def target_types() -> Iterable[type[Target]]:
    return (
        TypeScriptSourceTarget,
        TypeScriptSourcesGeneratorTarget,
        TypeScriptTestTarget,
        TypeScriptTestsGeneratorTarget,
    )
