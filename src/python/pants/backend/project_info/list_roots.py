# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import itertools
from pathlib import PurePath
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
    pattern_matches: Set[str] = set()
    for path in source_root_pattern_matcher.get_patterns():
        if path == "/":
            pattern_matches.add("**")
        elif path.startswith("/"):
            pattern_matches.add(f"{path[1:]}/")
        else:
            pattern_matches.add(f"**/{path}/")

    # Create globs for any marker files.
    marker_file_matches: Set[str] = set()
    for marker_filename in source_root_config.options.marker_filenames:
        marker_file_matches.add(f"**/{marker_filename}")

    # Match the patterns against actual files, to find the roots that actually exist.
    snapshots = await MultiGet(
        Get[Snapshot](PathGlobs(globs=sorted(pattern_matches))),
        Get[Snapshot](PathGlobs(globs=sorted(marker_file_matches))),
    )
    (pattern_snapshot, marker_file_snapshot) = snapshots

    responses = await MultiGet(
        itertools.chain(
            (
                Get[OptionalSourceRoot](SourceRootRequest(PurePath(d)))
                for d in pattern_snapshot.dirs
            ),
            # We don't technically need to issue a SourceRootRequest for the marker files,
            # since we know that their immediately enclosing dir is a source root by definition.
            # However we may as well verify this formally, so that we're not replicating that
            # logic here.
            (
                Get[OptionalSourceRoot](SourceRootRequest(PurePath(f)))
                for f in marker_file_snapshot.files
            ),
        )
    )
    all_source_roots = {
        response.source_root for response in responses if response.source_root is not None
    }
    return AllSourceRoots(all_source_roots)


@goal_rule
async def list_roots(console: Console, options: RootsOptions, asr: AllSourceRoots) -> Roots:
    with options.line_oriented(console) as print_stdout:
        for src_root in asr:
            print_stdout(src_root.path or ".")
    return Roots(exit_code=0)


def rules():
    return [all_roots, list_roots, SubsystemRule(SourceRootConfig)]
