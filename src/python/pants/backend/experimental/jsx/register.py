# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import Iterable

from pants.backend.jsx.goals import tailor
from pants.backend.jsx.target_types import JSXSourcesGeneratorTarget, JSXSourceTarget
from pants.engine.rules import Rule
from pants.engine.target import Target
from pants.engine.unions import UnionRule


def rules() -> Iterable[Rule | UnionRule]:
    return (*tailor.rules(),)


def target_types() -> Iterable[type[Target]]:
    return (
        JSXSourceTarget,
        JSXSourcesGeneratorTarget,
    )
