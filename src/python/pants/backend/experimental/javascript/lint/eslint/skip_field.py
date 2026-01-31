# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Skip field implementation for ESLint operations."""

from __future__ import annotations

from collections.abc import Iterable

from pants.backend.javascript.target_types import JSSourcesGeneratorTarget, JSSourceTarget
from pants.backend.tsx.target_types import TSXSourcesGeneratorTarget, TSXSourceTarget
from pants.backend.typescript.target_types import (
    TypeScriptSourcesGeneratorTarget,
    TypeScriptSourceTarget,
)
from pants.engine.rules import Rule
from pants.engine.target import BoolField
from pants.engine.unions import UnionRule


class SkipEslintField(BoolField):
    alias = "skip_eslint"
    default = False
    help = "If true, don't run ESLint on this target's code."


def rules() -> Iterable[Rule | UnionRule]:
    return (
        JSSourcesGeneratorTarget.register_plugin_field(SkipEslintField),
        JSSourceTarget.register_plugin_field(SkipEslintField),
        TypeScriptSourcesGeneratorTarget.register_plugin_field(SkipEslintField),
        TypeScriptSourceTarget.register_plugin_field(SkipEslintField),
        TSXSourcesGeneratorTarget.register_plugin_field(SkipEslintField),
        TSXSourceTarget.register_plugin_field(SkipEslintField),
    )
