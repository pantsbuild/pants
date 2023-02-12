# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import os.path
from dataclasses import dataclass
from typing import Iterable

from pants.backend.javascript import nodejs_project_environment
from pants.backend.javascript.nodejs_project import AllNodeJSProjects, NodeJSProject
from pants.backend.javascript.nodejs_project_environment import (
    NodeJsProjectEnvironment,
    NodeJsProjectEnvironmentProcess,
)
from pants.core.goals.generate_lockfiles import (
    GenerateLockfile,
    GenerateLockfileResult,
    KnownUserResolveNames,
    KnownUserResolveNamesRequest,
    RequestedUserResolveNames,
    UserGenerateLockfiles,
)
from pants.engine.internals.native_engine import AddPrefix, Digest
from pants.engine.internals.selectors import Get
from pants.engine.process import ProcessResult
from pants.engine.rules import Rule, collect_rules, rule
from pants.engine.unions import UnionRule


@dataclass(frozen=True)
class GeneratePackageLockJsonFile(GenerateLockfile):
    project: NodeJSProject


class KnownPackageJsonUserResolveNamesRequest(KnownUserResolveNamesRequest):
    pass


class RequestedPackageJsonUserResolveNames(RequestedUserResolveNames):
    pass


@rule
async def determine_package_json_user_resolves(
    _: KnownPackageJsonUserResolveNamesRequest, all_projects: AllNodeJSProjects
) -> KnownUserResolveNames:

    return KnownUserResolveNames(
        names=tuple(project.resolve_name for project in all_projects),
        option_name="<generated>",
        requested_resolve_names_cls=RequestedPackageJsonUserResolveNames,
    )


@rule
async def setup_user_lockfile_requests(
    requested: RequestedPackageJsonUserResolveNames, all_projects: AllNodeJSProjects
) -> UserGenerateLockfiles:
    projects_by_name = {project.resolve_name: project for project in all_projects}
    return UserGenerateLockfiles(
        GeneratePackageLockJsonFile(
            resolve_name=name,
            lockfile_dest=os.path.join(projects_by_name[name].root_dir, "package-lock.json"),
            diff=False,
            project=projects_by_name[name],
        )
        for name in requested
    )


@rule
async def generate_lockfile_from_package_jsons(
    request: GeneratePackageLockJsonFile,
) -> GenerateLockfileResult:
    result = await Get(
        ProcessResult,
        NodeJsProjectEnvironmentProcess(
            env=NodeJsProjectEnvironment.from_root(request.project),
            args=("install", "--package-lock-only"),
            description=f"generate package-lock.json for '{request.resolve_name}'.",
            output_files=("package-lock.json",),
        ),
    )
    output_digest = await Get(Digest, AddPrefix(result.output_digest, request.project.root_dir))
    return GenerateLockfileResult(output_digest, request.resolve_name, request.lockfile_dest)


def rules() -> Iterable[Rule | UnionRule]:
    return (
        *collect_rules(),
        *nodejs_project_environment.rules(),
        UnionRule(GenerateLockfile, GeneratePackageLockJsonFile),
        UnionRule(KnownUserResolveNamesRequest, KnownPackageJsonUserResolveNamesRequest),
        UnionRule(RequestedUserResolveNames, RequestedPackageJsonUserResolveNames),
    )
