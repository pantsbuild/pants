# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Iterable

from pants.backend.go.subsystems.golang import GolangSubsystem
from pants.core.util_rules import asdf
from pants.core.util_rules.asdf import AsdfToolPathsRequest, AsdfToolPathsResult
from pants.core.util_rules.environments import EnvironmentTarget, LocalEnvironmentTarget
from pants.engine.env_vars import EnvironmentVars, EnvironmentVarsRequest
from pants.engine.internals.selectors import Get
from pants.engine.rules import collect_rules, rule
from pants.util.strutil import softwrap

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GoBootstrap:
    go_search_paths: tuple[str, ...]


async def _go_search_paths(
    env_tgt: EnvironmentTarget, golang_subsystem: GolangSubsystem, paths: Iterable[str]
) -> tuple[str, ...]:
    resolve_standard, resolve_local = "<ASDF>" in paths, "<ASDF_LOCAL>" in paths

    if resolve_standard or resolve_local:
        # AsdfToolPathsResult is uncacheable, so only request it if absolutely necessary.
        asdf_result = await Get(
            AsdfToolPathsResult,
            AsdfToolPathsRequest(
                env_tgt=env_tgt,
                tool_name=golang_subsystem.asdf_tool_name,
                tool_description="Go distribution",
                resolve_standard=resolve_standard,
                resolve_local=resolve_local,
                paths_option_name="[golang].go_search_paths",
                bin_relpath=golang_subsystem.asdf_bin_relpath,
            ),
        )
        asdf_standard_tool_paths = asdf_result.standard_tool_paths
        asdf_local_tool_paths = asdf_result.local_tool_paths
    else:
        asdf_standard_tool_paths = ()
        asdf_local_tool_paths = ()

    special_strings = {
        "<ASDF>": lambda: asdf_standard_tool_paths,
        "<ASDF_LOCAL>": lambda: asdf_local_tool_paths,
    }

    expanded: list[str] = []
    for s in paths:
        if s == "<PATH>":
            expanded.extend(await _environment_paths())
        elif s in special_strings:
            special_paths = special_strings[s]()
            expanded.extend(special_paths)
        else:
            expanded.append(s)
    return tuple(expanded)


async def _environment_paths() -> list[str]:
    """Returns a list of paths specified by the PATH env var."""
    env = await Get(EnvironmentVars, EnvironmentVarsRequest(("PATH",)))
    path = env.get("PATH")
    if path:
        return path.split(os.pathsep)
    return []


def _error_if_not_compatible_with_asdf(
    env_tgt: EnvironmentTarget,
    _search_paths: Iterable[str],
) -> None:
    """Raises an exception if any special search path strings any are invalid for the environment.

    If the environment is non-local and there are invalid tokens for those environments, raise
    `ValueError`.
    """

    env = env_tgt.val

    if env is None or isinstance(env, LocalEnvironmentTarget):
        return

    not_allowed = {"<ASDF>", "<ASDF_LOCAL>"}

    any_not_allowed = set(_search_paths) & not_allowed
    if any_not_allowed:
        env_type = type(env)
        raise ValueError(
            softwrap(
                f"`[python-bootstrap].search_paths` is configured to use local Go discovery "
                f"tools, which do not work in {env_type.__name__} runtime environments. To fix "
                f"this, set the value of `golang_go_search_paths` in the `{env.alias}` "
                f"defined at `{env.address}` to contain only hardcoded paths or the `<PATH>` "
                "special string."
            )
        )

    return


@rule
async def resolve_go_bootstrap(
    golang_subsystem: GolangSubsystem, golang_env_aware: GolangSubsystem.EnvironmentAware
) -> GoBootstrap:
    _error_if_not_compatible_with_asdf(
        golang_env_aware.env_tgt, golang_env_aware.raw_go_search_paths
    )
    paths = await _go_search_paths(
        golang_env_aware.env_tgt, golang_subsystem, golang_env_aware.raw_go_search_paths
    )

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
        major, minor = v.split(".", maxsplit=1)
        return int(major), int(minor)

    return parse(target_version) <= parse(compiler_version)


def rules():
    return (
        *collect_rules(),
        *asdf.rules(),
    )
