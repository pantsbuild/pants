# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import itertools
import os.path
from dataclasses import dataclass
from typing import Iterable

from pants.backend.javascript import package_json
from pants.backend.javascript.import_parser.rules import JSImportStrings, ParseJsImportStrings
from pants.backend.javascript.import_parser.rules import rules as import_parser_rules
from pants.backend.javascript.package_json import (
    AllPackageJson,
    FirstPartyNodePackageTargets,
    NodePackageDependenciesField,
    NodePackageNameField,
    OwningNodePackage,
    OwningNodePackageRequest,
    PackageJsonEntryPoints,
    PackageJsonForGlobs,
    PackageJsonSourceField,
)
from pants.backend.javascript.target_types import JSDependenciesField, JSSourceField
from pants.build_graph.address import Address
from pants.engine.addresses import Addresses
from pants.engine.fs import PathGlobs
from pants.engine.internals.graph import Owners, OwnersRequest
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import Rule, collect_rules, rule
from pants.engine.target import FieldSet, InferDependenciesRequest, InferredDependencies, Targets
from pants.engine.unions import UnionRule
from pants.option.global_options import UnmatchedBuildFileGlobs
from pants.util.frozendict import FrozenDict
from pants.util.ordered_set import FrozenOrderedSet


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
    entry_points = PackageJsonEntryPoints.from_package_json(pkg_json)

    candidate_js_files, candidate_pkg_files = await MultiGet(
        Get(Owners, OwnersRequest(tuple(entry_points.globs_relative_to(pkg_json)))),
        Get(
            Owners,
            OwnersRequest(tuple(pkg.file for pkg in all_pkg_json if pkg_json in pkg.workspaces)),
        ),
    )
    js_targets, pkg_targets = await MultiGet(
        Get(Targets, Addresses(candidate_js_files)), Get(Targets, Addresses(candidate_pkg_files))
    )
    return InferredDependencies(
        itertools.chain(
            (tgt.address for tgt in pkg_targets if tgt.has_field(PackageJsonSourceField)),
            (tgt.address for tgt in js_targets if tgt.has_field(JSSourceField)),
        )
    )


class NodePackageCandidateMap(FrozenDict[str, Address]):
    pass


@dataclass(frozen=True)
class RequestNodePackagesCandidateMap:
    address: Address


@rule
async def map_candidate_node_packages(
    req: RequestNodePackagesCandidateMap, first_party: FirstPartyNodePackageTargets
) -> NodePackageCandidateMap:
    owning_pkg = await Get(OwningNodePackage, OwningNodePackageRequest(req.address))
    candidate_tgts = itertools.chain(
        first_party, owning_pkg.third_party if owning_pkg != OwningNodePackage.no_owner() else ()
    )
    return NodePackageCandidateMap(
        (tgt[NodePackageNameField].value, tgt.address) for tgt in candidate_tgts
    )


@rule
async def infer_js_source_dependencies(
    request: InferJSDependenciesRequest,
) -> InferredDependencies:
    source: JSSourceField = request.field_set.source
    import_strings = await Get(JSImportStrings, ParseJsImportStrings(source))
    path_strings = FrozenOrderedSet(
        os.path.normpath(os.path.join(os.path.dirname(source.file_path), import_string))
        for import_string in import_strings
        if import_string.startswith((os.path.curdir, os.path.pardir))
    )

    owners = await Get(Owners, OwnersRequest(tuple(path_strings)))
    owning_targets = await Get(Targets, Addresses(owners))

    non_path_string_bases = FrozenOrderedSet(
        os.path.basename(non_path_string) for non_path_string in import_strings - path_strings
    )
    candidate_pkgs = await Get(
        NodePackageCandidateMap, RequestNodePackagesCandidateMap(request.field_set.address)
    )

    pkg_addresses = (
        candidate_pkgs[pkg_name] for pkg_name in non_path_string_bases if pkg_name in candidate_pkgs
    )

    return InferredDependencies(
        itertools.chain(
            pkg_addresses,
            (tgt.address for tgt in owning_targets if tgt.has_field(JSSourceField)),
        )
    )


def rules() -> Iterable[Rule | UnionRule]:
    return [
        *collect_rules(),
        *package_json.rules(),
        *import_parser_rules(),
        UnionRule(InferDependenciesRequest, InferNodePackageDependenciesRequest),
        UnionRule(InferDependenciesRequest, InferJSDependenciesRequest),
    ]
