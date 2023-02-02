# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from pants.backend.javascript import package_json
from pants.backend.javascript.package_json import (
    AllPackageJson,
    NodePackageDependenciesField,
    PackageJsonForGlobs,
    PackageJsonSourceField,
)
from pants.engine.fs import PathGlobs
from pants.engine.internals.graph import Owners, OwnersRequest
from pants.engine.internals.selectors import Get
from pants.engine.rules import Rule, collect_rules, rule
from pants.engine.target import FieldSet, InferDependenciesRequest, InferredDependencies
from pants.engine.unions import UnionRule
from pants.option.global_options import UnmatchedBuildFileGlobs


@dataclass(frozen=True)
class NodePackageInferenceFieldSet(FieldSet):
    required_fields = (PackageJsonSourceField, NodePackageDependenciesField)

    source: PackageJsonSourceField
    dependencies: NodePackageDependenciesField


class InferNodePackageDependenciesRequest(InferDependenciesRequest):
    infer_from = NodePackageInferenceFieldSet


@rule
async def infer_node_package_dependencies(
    request: InferNodePackageDependenciesRequest, all_pkg_json: AllPackageJson
) -> InferredDependencies:
    source: PackageJsonSourceField = request.field_set.source
    [pkg_json] = await Get(
        PackageJsonForGlobs, PathGlobs, source.path_globs(UnmatchedBuildFileGlobs.error)
    )
    addresses = await Get(
        Owners,
        OwnersRequest(tuple(pkg.file for pkg in all_pkg_json if pkg_json in pkg.workspaces)),
    )
    return InferredDependencies(addresses)


def rules() -> Iterable[Rule | UnionRule]:
    return [
        *collect_rules(),
        *package_json.rules(),
        UnionRule(InferDependenciesRequest, InferNodePackageDependenciesRequest),
    ]
