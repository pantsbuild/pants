# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations
from collections.abc import Iterable

from pants.base.specs import Specs
from pants.engine.console import Console
from pants.engine.fs import PathMetadataRequest, PathMetadataResult, Workspace
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.internals.build_files import BuildFileOptions
from pants.engine.internals.native_engine import PathMetadata, PathNamespace
from pants.engine.internals.selectors import Get
from pants.engine.rules import Rule, collect_rules, goal_rule
from pants.engine.unions import UnionMembership
from pants.option.option_types import StrOption


class XMetadataSubsystem(GoalSubsystem):
    name = "x-metadata"
    help = """No help at all."""

    path = StrOption(default=None, help="No help at all.")


class XMetadataGoal(Goal):
    subsystem_cls = XMetadataSubsystem
    environment_behavior = Goal.EnvironmentBehavior.LOCAL_ONLY


@goal_rule
async def x_metadata(
    metadata_subsystem: XMetadataSubsystem,
    console: Console,
    workspace: Workspace,
    union_membership: UnionMembership,
    specs: Specs,
    build_file_options: BuildFileOptions,
) -> XMetadataGoal:
    path = metadata_subsystem.path
    if path is None:
        raise ValueError("Specify a path!")
    
    result = await Get(PathMetadataResult, PathMetadataRequest(path, PathNamespace.SYSTEM))
    console.write_stdout(f"path: {path}\n")
    console.write_stdout(f"metadata: {result.metadata}\n")

    return XMetadataGoal(0)


def rules() -> Iterable[Rule]:
    return collect_rules()
