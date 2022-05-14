# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import Iterable

from pants.backend.javascript.goals import tailor
from pants.backend.javascript.subsystems import nodejs
from pants.backend.javascript.target_types import JSSourcesGeneratorTarget, JSSourceTarget
from pants.engine.rules import Rule
from pants.engine.target import Target
from pants.engine.unions import UnionRule


def rules() -> Iterable[Rule | UnionRule]:
    return (
        *nodejs.rules(),
        *tailor.rules(),
    )


def target_types() -> Iterable[type[Target]]:
    return (
        JSSourceTarget,
        JSSourcesGeneratorTarget,
    )
