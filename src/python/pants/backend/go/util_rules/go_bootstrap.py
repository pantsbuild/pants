# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Collection

from pants.backend.go.subsystems.golang import GolangSubsystem
from pants.core.util_rules import asdf, search_paths
from pants.core.util_rules.asdf import AsdfPathString, AsdfToolPathsResult
from pants.core.util_rules.environments import EnvironmentTarget
from pants.core.util_rules.search_paths import ValidatedSearchPaths, ValidateSearchPathsRequest
from pants.engine.env_vars import PathEnvironmentVariable
from pants.engine.internals.selectors import Get
from pants.engine.rules import collect_rules, rule
from pants.util.ordered_set import FrozenOrderedSet

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GoBootstrap:
    go_search_paths: tuple[str, ...]


async def _go_search_paths(
    env_tgt: EnvironmentTarget, golang_subsystem: GolangSubsystem, paths: Collection[str]
) -> tuple[str, ...]:
    asdf_result = await AsdfToolPathsResult.get_un_cachable_search_paths(
        paths,
        env_tgt=env_tgt,
        tool_name=golang_subsystem.asdf_tool_name,
        tool_description="Go distribution",
        paths_option_name="[golang].go_search_paths",
        bin_relpath=golang_subsystem.asdf_bin_relpath,
    )
    special_strings = {
        AsdfPathString.STANDARD.value: asdf_result.standard_tool_paths,
        AsdfPathString.LOCAL.value: asdf_result.local_tool_paths,
    }

    path_variables = await Get(PathEnvironmentVariable)
    expanded: list[str] = []
    for s in paths:
        if s == "<PATH>":
            expanded.extend(path_variables)
        elif s in special_strings:
            special_paths = special_strings[s]
            expanded.extend(special_paths)
        else:
            expanded.append(s)
    return tuple(expanded)


@rule
async def resolve_go_bootstrap(
    golang_subsystem: GolangSubsystem, golang_env_aware: GolangSubsystem.EnvironmentAware
) -> GoBootstrap:
    search_paths = await Get(
        ValidatedSearchPaths,
        ValidateSearchPathsRequest(
            env_tgt=golang_env_aware.env_tgt,
            search_paths=tuple(golang_env_aware.raw_go_search_paths),
            option_origin=f"[{GolangSubsystem.options_scope}].go_search_paths",
            environment_key="golang_go_search_paths",
            is_default=golang_env_aware._is_default("_go_search_paths"),
            local_only=FrozenOrderedSet((AsdfPathString.STANDARD, AsdfPathString.LOCAL)),
        ),
    )
    paths = await _go_search_paths(golang_env_aware.env_tgt, golang_subsystem, search_paths)

    return GoBootstrap(go_search_paths=paths)


def compatible_go_version(*, compiler_version: str, target_version: str) -> bool:
    """Can the Go compiler handle the target version?

    Inspired by
    https://github.com/golang/go/blob/30501bbef9fcfc9d53e611aaec4d20bb3cdb8ada/src/cmd/go/internal/work/exec.go#L429-L445.

    Input expected in the form `1.17`.
    """
    if target_version == "1.0":
        return True

    def parse(v: str) -> tuple[int, int]:
        parts = v.split(".", maxsplit=2)
        major, minor = parts[0], parts[1]
        return int(major), int(minor)

    return parse(target_version) <= parse(compiler_version)


def rules():
    return (
        *collect_rules(),
        *asdf.rules(),
        *search_paths.rules(),
    )
