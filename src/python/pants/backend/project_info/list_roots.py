# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Set

from pants.engine.console import Console
from pants.engine.fs import PathGlobs, Snapshot
from pants.engine.goal import Goal, GoalSubsystem, LineOriented
from pants.engine.rules import SubsystemRule, goal_rule, rule
from pants.engine.selectors import Get, MultiGet
from pants.source.source_root import (
    AllSourceRoots,
    OptionalSourceRoot,
    SourceRootConfig,
    SourceRootRequest,
)


class RootsOptions(LineOriented, GoalSubsystem):
    """List the repo's registered source roots."""

    name = "roots"


class Roots(Goal):
    subsystem_cls = RootsOptions


@rule
async def all_roots(source_root_config: SourceRootConfig) -> AllSourceRoots:
    source_root_pattern_matcher = source_root_config.get_pattern_matcher()

    # Create globs corresponding to all source root patterns.
    all_paths: Set[str] = set()
    for path in source_root_pattern_matcher.get_patterns():
        if path == "/":
            all_paths.add("**")
        elif path.startswith("/"):
            all_paths.add(f"{path[1:]}/")
        else:
            all_paths.add(f"**/{path}/")

    # Match the patterns against actual files, to find the roots that actually exist.
    snapshot = await Get[Snapshot](PathGlobs(globs=sorted(all_paths)))
    responses = await MultiGet(Get[OptionalSourceRoot](SourceRootRequest(d)) for d in snapshot.dirs)
    all_source_roots = {
        response.source_root for response in responses if response.source_root is not None
    }
    return AllSourceRoots(all_source_roots)


@goal_rule
async def list_roots(console: Console, options: RootsOptions, asr: AllSourceRoots) -> Roots:
    with options.line_oriented(console) as print_stdout:
        for src_root in sorted(asr, key=lambda x: x.path):
            print_stdout(src_root.path or ".")
    return Roots(exit_code=0)


def rules():
    return [all_roots, list_roots, SubsystemRule(SourceRootConfig)]
