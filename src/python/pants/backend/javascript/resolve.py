# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable

from pants.backend.javascript import nodejs_project
from pants.backend.javascript.nodejs_project import AllNodeJSProjects, NodeJSProject
from pants.backend.javascript.package_json import (
    NodePackageNameField,
    OwningNodePackage,
    OwningNodePackageRequest,
    PackageJsonSourceField,
)
from pants.build_graph.address import Address
from pants.engine.fs import PathGlobs
from pants.engine.internals.selectors import Get
from pants.engine.rules import Rule, collect_rules, rule
from pants.engine.target import Target, WrappedTarget, WrappedTargetRequest
from pants.engine.unions import UnionRule


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


def rules() -> Iterable[Rule | UnionRule]:
    return [*collect_rules(), *nodejs_project.rules()]
