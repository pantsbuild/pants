# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import Iterable

# from pants.backend.cc.dependency_inference.rules import rules as dep_inf_rules
from pants.backend.js.goals import tailor

# from pants.backend.js.rules import rules as js_rules
from pants.backend.js.target_types import JSSourcesGeneratorTarget, JSSourceTarget

# from pants.backend.js.target_types import rules as target_type_rules
from pants.engine.rules import Rule
from pants.engine.target import Target
from pants.engine.unions import UnionRule


def rules() -> Iterable[Rule | UnionRule]:
    return (
        # *dep_inf_rules(),
        *tailor.rules(),
        # *target_type_rules(),
    )


def target_types() -> Iterable[type[Target]]:
    return (
        JSSourceTarget,
        JSSourcesGeneratorTarget,
    )
