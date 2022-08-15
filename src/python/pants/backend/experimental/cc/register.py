# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import Iterable

from pants.backend.cc.dependency_inference.rules import rules as dep_inf_rules
from pants.backend.cc.goals import check, package, tailor
from pants.backend.cc.subsystems import toolchain
from pants.backend.cc.target_types import (
    CCBinaryTarget,
    CCLibraryTarget,
    CCSourcesGeneratorTarget,
    CCSourceTarget,
)
from pants.backend.cc.target_types import rules as target_type_rules
from pants.backend.cc.util_rules import compile, link
from pants.engine.rules import Rule
from pants.engine.unions import UnionRule


def target_types():
    return (
        CCSourceTarget,
        CCSourcesGeneratorTarget,
        CCBinaryTarget,
        CCLibraryTarget,
    )


def rules() -> Iterable[Rule | UnionRule]:
    return (
        *check.rules(),
        *compile.rules(),
        *dep_inf_rules(),
        *link.rules(),
        *package.rules(),
        *tailor.rules(),
        *toolchain.rules(),
        *target_type_rules(),
    )
