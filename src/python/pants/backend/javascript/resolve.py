# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable

from pants.backend.javascript import nodejs_project
from pants.backend.javascript.nodejs_project import AllNodeJSProjects, NodeJSProject
from pants.backend.javascript.package_json import (
    FirstPartyNodePackageTargets,
    NodePackageNameField,
    OwningNodePackage,
    OwningNodePackageRequest,
    PackageJsonSourceField,
)
from pants.backend.javascript.subsystems.nodejs import UserChosenNodeJSResolveAliases
from pants.build_graph.address import Address
from pants.engine.fs import PathGlobs
from pants.engine.internals.selectors import Get
from pants.engine.rules import Rule, collect_rules, rule
from pants.engine.target import Target, WrappedTarget, WrappedTargetRequest
from pants.engine.unions import UnionRule
from pants.util.frozendict import FrozenDict


@dataclass(frozen=True)
class RequestNodeResolve:
    address: Address


@dataclass(frozen=True)
class ChosenNodeResolve:
    project: NodeJSProject

    @property
    def resolve_name(self) -> str:
        return self.project.default_resolve_name

    @property
    def file_path(self) -> str:
        return os.path.join(self.project.root_dir, self.project.lockfile_name)

    def get_lockfile_glob(self) -> PathGlobs:
        return PathGlobs([self.file_path])


async def _get_node_package_json_directory(req: RequestNodeResolve) -> str:
    wrapped = await Get(
        WrappedTarget,
        WrappedTargetRequest(req.address, description_of_origin="the `ChosenNodeResolve` rule"),
    )
    target: Target | None
    if wrapped.target.has_field(PackageJsonSourceField) and wrapped.target.has_field(
        NodePackageNameField
    ):
        target = wrapped.target
    else:
        owning_pkg = await Get(OwningNodePackage, OwningNodePackageRequest(wrapped.target.address))
        target = owning_pkg.ensure_owner()
    return os.path.dirname(target[PackageJsonSourceField].file_path)


@rule
async def resolve_for_package(
    req: RequestNodeResolve, all_projects: AllNodeJSProjects
) -> ChosenNodeResolve:
    directory = await _get_node_package_json_directory(req)
    project = all_projects.project_for_directory(directory)
    return ChosenNodeResolve(project)


class NodeJSProjectResolves(FrozenDict[str, NodeJSProject]):
    pass


@rule
async def resolve_to_projects(
    all_projects: AllNodeJSProjects, user_chosen_resolves: UserChosenNodeJSResolveAliases
) -> NodeJSProjectResolves:
    def get_name(project: NodeJSProject) -> str:
        return user_chosen_resolves.get(
            os.path.join(project.root_dir, project.lockfile_name), project.default_resolve_name
        )

    return NodeJSProjectResolves((get_name(project), project) for project in all_projects)


class FirstPartyNodePackageResolves(FrozenDict[str, Target]):
    pass


@rule
async def resolve_to_first_party_node_package(
    resolves: NodeJSProjectResolves, all_first_party: FirstPartyNodePackageTargets
) -> FirstPartyNodePackageResolves:
    by_dir = {first_party.residence_dir: first_party for first_party in all_first_party}
    return FirstPartyNodePackageResolves(
        (resolve, by_dir[project.root_dir]) for resolve, project in resolves.items()
    )


def rules() -> Iterable[Rule | UnionRule]:
    return [*collect_rules(), *nodejs_project.rules()]
