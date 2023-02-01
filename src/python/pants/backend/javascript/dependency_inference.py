# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from pants.backend.javascript import package_json
from pants.backend.javascript.package_json import (
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
    pkg_json = await Get(PackageJson, ReadPackageJsonRequest(request.field_set.source))
    workspace_files = {pkg.file for pkg in pkg_json.workspaces}
    addresses = (
        tgt.address for tgt in all_tgts if tgt[PackageJsonSourceField].file_path in workspace_files
    )
    return InferredDependencies(addresses)


def rules() -> Iterable[Rule | UnionRule]:
    return [
        *collect_rules(),
        *package_json.rules(),
        UnionRule(InferDependenciesRequest, InferPackageJsonDependenciesRequest),
    ]
