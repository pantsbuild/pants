# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import os.path
from dataclasses import dataclass
from typing import Iterable

from pants.backend.javascript import package_json
from pants.backend.javascript.import_parser.rules import JSImportStrings, ParseJsImportStrings
from pants.backend.javascript.import_parser.rules import rules as import_parser_rules
from pants.backend.javascript.package_json import (
    AllPackageJson,
    NodePackageDependenciesField,
    PackageJsonForGlobs,
    PackageJsonSourceField,
)
from pants.backend.javascript.target_types import JSDependenciesField, JSSourceField
from pants.engine.addresses import Addresses
from pants.engine.fs import PathGlobs
from pants.engine.internals.graph import Owners, OwnersRequest
from pants.engine.internals.selectors import Get
from pants.engine.rules import Rule, collect_rules, rule
from pants.engine.target import FieldSet, InferDependenciesRequest, InferredDependencies, Targets
from pants.engine.unions import UnionRule
from pants.option.global_options import UnmatchedBuildFileGlobs


@dataclass(frozen=True)
class NodePackageInferenceFieldSet(FieldSet):
    required_fields = (PackageJsonSourceField, NodePackageDependenciesField)

    source: PackageJsonSourceField
    dependencies: NodePackageDependenciesField


class InferNodePackageDependenciesRequest(InferDependenciesRequest):
    infer_from = NodePackageInferenceFieldSet


@dataclass(frozen=True)
class JSSourceInferenceFieldSet(FieldSet):
    required_fields = (JSSourceField, JSDependenciesField)

    source: JSSourceField
    dependencies: JSDependenciesField


class InferJSDependenciesRequest(InferDependenciesRequest):
    infer_from = JSSourceInferenceFieldSet


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


@rule
async def infer_js_source_dependencies(request: InferJSDependenciesRequest) -> InferredDependencies:
    source: JSSourceField = request.field_set.source
    import_strings = await Get(JSImportStrings, ParseJsImportStrings(source))
    path_strings = []
    for import_string in import_strings:
        if import_string.startswith((os.path.curdir, os.path.pardir)):
            path_strings.append(
                os.path.normpath(os.path.join(os.path.dirname(source.file_path), import_string))
            )

    owners = await Get(Owners, OwnersRequest(tuple(path_strings)))
    owning_targets = await Get(Targets, Addresses, Addresses(owners))

    return InferredDependencies(
        [tgt.address for tgt in owning_targets if tgt.has_field(JSSourceField)]
    )


def rules() -> Iterable[Rule | UnionRule]:
    return [
        *collect_rules(),
        *package_json.rules(),
        *import_parser_rules(),
        UnionRule(InferDependenciesRequest, InferNodePackageDependenciesRequest),
        UnionRule(InferDependenciesRequest, InferJSDependenciesRequest),
    ]
