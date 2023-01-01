# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import Iterable

from pants.backend.cc.target_types import CCSourcesGeneratorTarget, CCSourceTarget
from pants.engine.rules import Rule
from pants.engine.target import BoolField
from pants.engine.unions import UnionRule


class SkipClangFormatField(BoolField):
    alias = "skip_clang_format"
    default = False
    help = "If true, don't run clang-format on this target's code."


def rules() -> Iterable[Rule | UnionRule]:
    return (
        CCSourcesGeneratorTarget.register_plugin_field(SkipClangFormatField),
        CCSourceTarget.register_plugin_field(SkipClangFormatField),
    )
