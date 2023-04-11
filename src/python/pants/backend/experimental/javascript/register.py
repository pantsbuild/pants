# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import Iterable

from pants.backend.javascript import package_json
from pants.backend.javascript.goals import lockfile, tailor, test
from pants.backend.javascript.package.rules import rules as package_rules
from pants.backend.javascript.run.rules import rules as run_rules
from pants.backend.javascript.subsystems import nodejs
from pants.backend.javascript.target_types import (
    JSSourcesGeneratorTarget,
    JSSourceTarget,
    JSTestsGeneratorTarget,
    JSTestTarget,
)
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.engine.rules import Rule
from pants.engine.target import Target
from pants.engine.unions import UnionRule


def rules() -> Iterable[Rule | UnionRule]:
    return (
        *nodejs.rules(),
        *tailor.rules(),
        *lockfile.rules(),
        *package_rules(),
        *run_rules(),
        *test.rules(),
    )


def target_types() -> Iterable[type[Target]]:
    return (
        JSSourceTarget,
        JSSourcesGeneratorTarget,
        JSTestTarget,
        JSTestsGeneratorTarget,
        *package_json.target_types(),
    )


def build_file_aliases() -> BuildFileAliases:
    return package_json.build_file_aliases()
