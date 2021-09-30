# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging

from pants.backend.go.target_types import GoExternalPackageTarget, GoModSourcesField
from pants.backend.go.util_rules.build_go_pkg import BuildGoPackageRequest, BuiltGoPackage
from pants.backend.go.util_rules.external_module import ResolveExternalGoPackageRequest
from pants.backend.go.util_rules.go_mod import GoModInfo, GoModInfoRequest
from pants.backend.go.util_rules.go_pkg import (
    ResolvedGoPackage,
    ResolveGoPackageRequest,
    is_first_party_package_target,
    is_third_party_package_target,
)
from pants.engine.console import Console
from pants.engine.fs import MergeDigests, Snapshot, Workspace
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import collect_rules, goal_rule
from pants.engine.target import UnexpandedTargets

logger = logging.getLogger(__name__)


# TODO(12764): Add integration tests for the `go-resolve` goal once we figure out its final form.
#  For now, it is a debug tool to help update go.sum while developing the Go plugin and will probably change.
class GoResolveSubsystem(GoalSubsystem):
    name = "go-resolve"
    help = "Resolve a Go module's go.mod and update go.sum accordingly."


class GoResolveGoal(Goal):
    subsystem_cls = GoResolveSubsystem


@goal_rule
async def run_go_resolve(targets: UnexpandedTargets, workspace: Workspace) -> GoResolveGoal:
    all_go_mod_info = await MultiGet(
        Get(GoModInfo, GoModInfoRequest(target.address))
        for target in targets
        if target.has_field(GoModSourcesField)
    )
    result = await Get(
        Snapshot, MergeDigests(go_mod_info.digest for go_mod_info in all_go_mod_info)
    )
    logger.info(f"Updating these files: {list(result.files)}")
    # TODO: Only update the files if they actually changed.
    workspace.write_digest(result.digest)
    return GoResolveGoal(exit_code=0)


class GoBuildSubsystem(GoalSubsystem):
    name = "go-build"
    help = "Compile Go targets that contain source code (i.e., `go_package`)."


class GoBuildGoal(Goal):
    subsystem_cls = GoBuildSubsystem


@goal_rule
async def run_go_build(targets: UnexpandedTargets) -> GoBuildGoal:
    await MultiGet(
        Get(BuiltGoPackage, BuildGoPackageRequest(address=tgt.address))
        for tgt in targets
        if is_first_party_package_target(tgt) or is_third_party_package_target(tgt)
    )
    return GoBuildGoal(exit_code=0)


class GoPkgDebugSubsystem(GoalSubsystem):
    name = "go-pkg-debug"
    help = "Resolve a Go package and display its metadata"


class GoPkgDebugGoal(Goal):
    subsystem_cls = GoPkgDebugSubsystem


@goal_rule
async def run_go_pkg_debug(targets: UnexpandedTargets, console: Console) -> GoPkgDebugGoal:
    first_party_requests = [
        Get(ResolvedGoPackage, ResolveGoPackageRequest(address=tgt.address))
        for tgt in targets
        if is_first_party_package_target(tgt)
    ]

    third_party_requests = [
        Get(ResolvedGoPackage, ResolveExternalGoPackageRequest(tgt))
        for tgt in targets
        if isinstance(tgt, GoExternalPackageTarget)
    ]

    resolved_packages = await MultiGet([*first_party_requests, *third_party_requests])  # type: ignore
    for package in resolved_packages:
        console.write_stdout(str(package) + "\n")

    return GoPkgDebugGoal(exit_code=0)


def rules():
    return collect_rules()
