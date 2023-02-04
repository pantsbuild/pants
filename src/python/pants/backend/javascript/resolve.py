# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable

from pants.backend.javascript import package_json
from pants.backend.javascript.package_json import (
    AllPackageJson,
    NodePackageNameField,
    OwningNodePackage,
    OwningNodePackageRequest,
)
from pants.build_graph.address import Address
from pants.engine.internals.selectors import Get
from pants.engine.rules import Rule, collect_rules, rule
from pants.engine.target import WrappedTarget, WrappedTargetRequest
from pants.engine.unions import UnionRule
from pants.util.strutil import softwrap


@dataclass(frozen=True)
class RequestNodeResolve:
    address: Address


@dataclass(frozen=True)
class ChosenNodeResolve:
    resolve_name: str
    file_path: str


@rule
async def resolve_for_package(
    req: RequestNodeResolve, all_pkgs: AllPackageJson
) -> ChosenNodeResolve:
    wrapped = await Get(
        WrappedTarget,
        WrappedTargetRequest(req.address, description_of_origin="the `ChosenNodeResolve` rule"),
    )
    if wrapped.target.has_field(NodePackageNameField):
        name = wrapped.target[NodePackageNameField].value
    else:
        owning_pkg = await Get(OwningNodePackage, OwningNodePackageRequest(req.address))
        if owning_pkg.target:
            name = owning_pkg.target[NodePackageNameField].value
        else:
            raise ValueError(
                softwrap(
                    f"""
                    No node resolve was could be determined for {req.address}.

                    This probably means that there is no `package.json` in any parent directory of this target.
                    """
                )
            )
    root_pkg_json = all_pkgs.root_pkg_json(name)
    return ChosenNodeResolve(
        resolve_name=root_pkg_json.name,
        file_path=os.path.join(root_pkg_json.root_dir, "package-lock.json"),
    )


def rules() -> Iterable[Rule | UnionRule]:
    return [*collect_rules(), *package_json.rules()]
