# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import Iterable

from pants.backend.javascript.target_types import JSSourcesGeneratorTarget, JSSourceTarget
from pants.engine.rules import Rule
from pants.engine.target import BoolField
from pants.engine.unions import UnionRule


class SkipPrettierField(BoolField):
    alias = "skip_prettier"
    default = False
    help = "If true, don't run Prettier on this target's code."


def rules() -> Iterable[Rule | UnionRule]:
    return (
        JSSourcesGeneratorTarget.register_plugin_field(SkipPrettierField),
        JSSourceTarget.register_plugin_field(SkipPrettierField),
    )
