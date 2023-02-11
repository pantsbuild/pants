# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable

from pants.backend.javascript import nodejs_project
from pants.backend.javascript.nodejs_project import AllNodeJSProjects
from pants.backend.javascript.package_json import (
    OwningNodePackage,
    OwningNodePackageRequest,
    PackageJsonSourceField,
)
from pants.build_graph.address import Address
from pants.engine.internals.selectors import Get
from pants.engine.rules import Rule, collect_rules, rule
from pants.engine.target import Target, WrappedTarget, WrappedTargetRequest
from pants.engine.unions import UnionRule
from pants.util.strutil import softwrap


@dataclass(frozen=True)
class RequestNodeResolve:
    address: Address


@dataclass(frozen=True)
class ChosenNodeResolve:
    resolve_name: str
    file_path: str


async def _get_node_package_json_directory(req: RequestNodeResolve) -> str:
    wrapped = await Get(
        WrappedTarget,
        WrappedTargetRequest(req.address, description_of_origin="the `ChosenNodeResolve` rule"),
    )
    target: Target | None
    if wrapped.target.has_field(PackageJsonSourceField):
        target = wrapped.target
    else:
        owning_pkg = await Get(OwningNodePackage, OwningNodePackageRequest(wrapped.target.address))
        target = owning_pkg.target
    if target:
        return os.path.dirname(target[PackageJsonSourceField].file_path)
    raise ValueError(
        softwrap(
            f"""
            No node resolve could be determined for {req.address}.

            This probably means that there is no `package.json` in any parent directory of this target.
            """
        )
    )


@rule
async def resolve_for_package(
    req: RequestNodeResolve, all_projects: AllNodeJSProjects
) -> ChosenNodeResolve:
    directory = await _get_node_package_json_directory(req)
    project = all_projects.project_for_directory(directory)
    return ChosenNodeResolve(
        resolve_name=project.resolve_name,
        file_path=os.path.join(project.root_dir, "package-lock.json"),
    )


def rules() -> Iterable[Rule | UnionRule]:
    return [*collect_rules(), *nodejs_project.rules()]
