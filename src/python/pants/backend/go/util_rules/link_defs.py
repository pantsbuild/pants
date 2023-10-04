# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass

from pants.backend.go.util_rules.build_opts import GoBuildOptions
from pants.engine.environment import EnvironmentName
from pants.engine.internals.native_engine import Digest
from pants.engine.rules import collect_rules
from pants.engine.unions import union
from pants.util.frozendict import FrozenDict


@union(in_scope_types=[EnvironmentName])
@dataclass(frozen=True)
class ImplicitLinkerDependenciesHook:
    build_opts: GoBuildOptions


@dataclass(frozen=True)
class ImplicitLinkerDependencies:
    digest: Digest
    import_paths_to_pkg_a_files: FrozenDict[str, str]


def rules():
    return collect_rules()
