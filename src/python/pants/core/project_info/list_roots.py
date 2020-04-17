# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Set

from pants.engine.console import Console
from pants.engine.fs import PathGlobs, Snapshot
from pants.engine.goal import Goal, GoalSubsystem, LineOriented
from pants.engine.rules import goal_rule, rule, subsystem_rule
from pants.engine.selectors import Get
from pants.source.source_root import AllSourceRoots, SourceRoot, SourceRootConfig


class RootsOptions(LineOriented, GoalSubsystem):
    """List the repo's registered source roots."""

    name = "roots"


class Roots(Goal):
    subsystem_cls = RootsOptions


@rule
async def all_roots(source_root_config: SourceRootConfig) -> AllSourceRoots:

    source_roots = source_root_config.get_source_roots()

    all_paths: Set[str] = set()
    for path in source_roots.traverse():
        if path == "^":
            all_paths.add("**")
        elif path.startswith("^/"):
            all_paths.add(f"{path[2:]}/")
        else:
            all_paths.add(f"**/{path}/")

    snapshot = await Get[Snapshot](PathGlobs(globs=sorted(all_paths)))

    all_source_roots: Set[SourceRoot] = set()

    # The globs above can match on subdirectories of the source roots.
    # For instance, `src/*/` might match 'src/rust/' as well as
    # 'src/rust/engine/process_execution/bazel_protos/src/gen'.
    # So we use find_by_path to verify every candidate source root.
    for directory in snapshot.dirs:
        match: SourceRoot = source_roots.find_by_path(directory)
        if match:
            all_source_roots.add(match)

    return AllSourceRoots(all_source_roots)


@goal_rule
async def list_roots(console: Console, options: RootsOptions, all_roots: AllSourceRoots) -> Roots:
    with options.line_oriented(console) as print_stdout:
        for src_root in sorted(all_roots, key=lambda x: x.path):
            all_langs = ",".join(sorted(src_root.langs))
            print_stdout(f"{src_root.path or '.'}: {all_langs or '*'}")
    return Roots(exit_code=0)


def rules():
    return [all_roots, list_roots, subsystem_rule(SourceRootConfig)]
