# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from pants.backend.go.subsystems.golang import GolangSubsystem
from pants.core.util_rules import asdf
from pants.core.util_rules.asdf import AsdfToolPathsRequest, AsdfToolPathsResult
from pants.engine.environment import Environment
from pants.engine.internals.selectors import Get
from pants.engine.rules import collect_rules, rule

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GoBootstrap:
    EXTRA_ENV_VAR_NAMES = ("PATH",)

    raw_go_search_paths: tuple[str, ...]
    environment: Environment
    asdf_standard_tool_paths: tuple[str, ...]
    asdf_local_tool_paths: tuple[str, ...]

    @property
    def go_search_paths(self) -> tuple[str, ...]:
        special_strings = {
            "<PATH>": lambda: GoBootstrap.get_environment_paths(self.environment),
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

    @staticmethod
    def get_environment_paths(env: Environment) -> list[str]:
        """Returns a list of paths specified by the PATH env var."""
        pathstr = env.get("PATH")
        if pathstr:
            return pathstr.split(os.pathsep)
        return []


@rule
async def resolve_go_bootstrap(golang_subsystem: GolangSubsystem) -> GoBootstrap:
    raw_go_search_paths = golang_subsystem.raw_go_search_paths
    result = await Get(
        AsdfToolPathsResult,
        AsdfToolPathsRequest(
            tool_name=golang_subsystem.asdf_tool_name,
            tool_description="Go distribution",
            resolve_standard="<ASDF>" in raw_go_search_paths,
            resolve_local="<ASDF_LOCAL>" in raw_go_search_paths,
            extra_env_var_names=("PATH",),
            paths_option_name="[golang].go_search_paths",
            bin_relpath=golang_subsystem.asdf_bin_relpath,
        ),
    )

    return GoBootstrap(
        raw_go_search_paths=raw_go_search_paths,
        environment=result.env,
        asdf_standard_tool_paths=result.standard_tool_paths,
        asdf_local_tool_paths=result.local_tool_paths,
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
