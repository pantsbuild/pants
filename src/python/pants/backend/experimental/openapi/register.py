# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import Iterable

from pants.backend.openapi import dependency_inference
from pants.backend.openapi.goals import tailor
from pants.backend.openapi.target_types import (
    OpenApiDocumentGeneratorTarget,
    OpenApiDocumentTarget,
    OpenApiSourceGeneratorTarget,
    OpenApiSourceTarget,
    OpenApiBundleTarget
)
from pants.backend.openapi.target_types import rules as target_types_rules
from pants.backend.openapi.util_rules import openapi_bundle
from pants.engine.rules import Rule
from pants.engine.target import Target
from pants.engine.unions import UnionRule


def rules() -> Iterable[Rule | UnionRule]:
    return [
        *dependency_inference.rules(),
        *openapi_bundle.rules(),
        *tailor.rules(),
        *target_types_rules(),
    ]


def target_types() -> Iterable[type[Target]]:
    return (
        OpenApiDocumentTarget,
        OpenApiDocumentGeneratorTarget,
        OpenApiSourceTarget,
        OpenApiSourceGeneratorTarget,
        OpenApiBundleTarget
    )
