# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from pants.backend.javascript import package_json
from pants.backend.javascript.package_json import (
    AllPackageJson,
    AllPackageJsonTargets,
    PackageJson,
    PackageJsonDependenciesField,
    PackageJsonSourceField,
    ReadPackageJsonRequest,
)
from pants.engine.internals.selectors import Get
from pants.engine.rules import Rule, collect_rules, rule
from pants.engine.target import FieldSet, InferDependenciesRequest, InferredDependencies
from pants.engine.unions import UnionRule


@dataclass(frozen=True)
class PackageJsonInferenceFieldSet(FieldSet):
    required_fields = (PackageJsonSourceField, PackageJsonDependenciesField)

    source: PackageJsonSourceField
    dependencies: PackageJsonDependenciesField


class InferPackageJsonDependenciesRequest(InferDependenciesRequest):
    infer_from = PackageJsonInferenceFieldSet


@rule
async def infer_package_json_dependencies(
    request: InferPackageJsonDependenciesRequest, all_tgts: AllPackageJsonTargets
) -> InferredDependencies:
    all_pkg_json = await Get(AllPackageJson, AllPackageJsonTargets, all_tgts)
    pkg_json = await Get(PackageJson, ReadPackageJsonRequest(request.field_set.source))
    addresses = {
        tgt.address for pkg, tgt in zip(all_pkg_json, all_tgts) if pkg_json in pkg.workspaces
    }
    return InferredDependencies(addresses)


def rules() -> Iterable[Rule | UnionRule]:
    return [
        *collect_rules(),
        *package_json.rules(),
        UnionRule(InferDependenciesRequest, InferPackageJsonDependenciesRequest),
    ]
