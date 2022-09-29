# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from pants.backend.go.subsystems.golang import GolangSubsystem
from pants.core.util_rules import asdf
from pants.core.util_rules.asdf import AsdfToolPathsRequest, AsdfToolPathsResult
from pants.engine.env_vars import EnvironmentVars, EnvironmentVarsRequest
from pants.engine.internals.selectors import Get
from pants.engine.rules import collect_rules, rule

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GoBootstrap:
    raw_go_search_paths: tuple[str, ...]
    asdf_standard_tool_paths: tuple[str, ...]
    asdf_local_tool_paths: tuple[str, ...]
    _path: str | None

    @property
    def go_search_paths(self) -> tuple[str, ...]:
        special_strings = {
            "<PATH>": lambda: self.environment_paths,
            "<ASDF>": lambda: self.asdf_standard_tool_paths,
            "<ASDF_LOCAL>": lambda: self.asdf_local_tool_paths,
        }
        expanded: list[str] = []
        for s in self.raw_go_search_paths:
            if s in special_strings:
                special_paths = special_strings[s]()
                expanded.extend(special_paths)
            else:
                expanded.append(s)
        return tuple(expanded)

    @property
    def environment_paths(self) -> list[str]:
        """Returns a list of paths specified by the PATH env var."""
        if self._path:
            return self._path.split(os.pathsep)
        return []


@rule
async def resolve_go_bootstrap(
    golang_subsystem: GolangSubsystem, golang_env_aware: GolangSubsystem.EnvironmentAware
) -> GoBootstrap:
    raw_go_search_paths = golang_env_aware.raw_go_search_paths
    result = await Get(
        AsdfToolPathsResult,
        AsdfToolPathsRequest(
            tool_name=golang_subsystem.asdf_tool_name,
            tool_description="Go distribution",
            resolve_standard="<ASDF>" in raw_go_search_paths,
            resolve_local="<ASDF_LOCAL>" in raw_go_search_paths,
            paths_option_name="[golang].go_search_paths",
            extra_env_var_names=(),
            bin_relpath=golang_subsystem.asdf_bin_relpath,
        ),
    )

    env = await Get(EnvironmentVars, EnvironmentVarsRequest(("PATH",)))

    return GoBootstrap(
        raw_go_search_paths=raw_go_search_paths,
        asdf_standard_tool_paths=result.standard_tool_paths,
        asdf_local_tool_paths=result.local_tool_paths,
        _path=env.get("PATH", None),
    )


def compatible_go_version(*, compiler_version: str, target_version: str) -> bool:
    """Can the Go compiler handle the target version?

    Inspired by
    https://github.com/golang/go/blob/30501bbef9fcfc9d53e611aaec4d20bb3cdb8ada/src/cmd/go/internal/work/exec.go#L429-L445.

    Input expected in the form `1.17`.
    """
    if target_version == "1.0":
        return True

    def parse(v: str) -> tuple[int, int]:
        major, minor = v.split(".", maxsplit=1)
        return int(major), int(minor)

    return parse(target_version) <= parse(compiler_version)


def rules():
    return (
        *collect_rules(),
        *asdf.rules(),
    )
