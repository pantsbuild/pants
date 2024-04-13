# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import Iterable

from pants.backend.python.target_types import (
    PythonSourcesGeneratorTarget,
    PythonSourceTarget,
    PythonTestsGeneratorTarget,
    PythonTestTarget,
    PythonTestUtilsGeneratorTarget,
)
from pants.engine.rules import Rule
from pants.engine.target import BoolField
from pants.engine.unions import UnionRule


class SkipPyrightField(BoolField):
    alias = "skip_pyright"
    default = False
    help = "If true, don't run Pyright on this target's code."


def rules() -> Iterable[Rule | UnionRule]:
    return (
        PythonSourcesGeneratorTarget.register_plugin_field(SkipPyrightField),
        PythonSourceTarget.register_plugin_field(SkipPyrightField),
        PythonTestsGeneratorTarget.register_plugin_field(SkipPyrightField),
        PythonTestTarget.register_plugin_field(SkipPyrightField),
        PythonTestUtilsGeneratorTarget.register_plugin_field(SkipPyrightField),
    )
