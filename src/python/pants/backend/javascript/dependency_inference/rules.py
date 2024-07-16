# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import itertools
import os.path
from dataclasses import dataclass
from typing import Iterable

from pants.backend.javascript import package_json
from pants.backend.javascript.package_json import (
    FirstPartyNodePackageTargets,
    NodePackageDependenciesField,
    NodePackageNameField,
    OwningNodePackage,
    OwningNodePackageRequest,
    PackageJsonEntryPoints,
    PackageJsonImports,
    PackageJsonSourceField,
    find_owning_package,
    subpath_imports_for_source,
)
from pants.backend.javascript.subsystems.nodejs_infer import NodeJSInfer
from pants.backend.javascript.target_types import JSDependenciesField, JSSourceField
from pants.backend.typescript import tsconfig
from pants.backend.typescript.tsconfig import ParentTSConfigRequest, TSConfig, find_parent_ts_config
from pants.build_graph.address import Address
from pants.engine.addresses import Addresses
from pants.engine.internals.graph import Owners, OwnersRequest
from pants.engine.internals.native_dep_inference import NativeParsedJavascriptDependencies
from pants.engine.internals.native_engine import InferenceMetadata, NativeDependenciesRequest
from pants.engine.internals.selectors import Get, concurrently
from pants.engine.rules import Rule, collect_rules, implicitly, rule
from pants.engine.target import (
    FieldSet,
    HydratedSources,
    HydrateSourcesRequest,
    InferDependenciesRequest,
    InferredDependencies,
    Targets,
)
from pants.engine.unions import UnionRule
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
    request: InferNodePackageDependenciesRequest,
    nodejs_infer: NodeJSInfer,
) -> InferredDependencies:
    if not nodejs_infer.package_json_entry_points:
        return InferredDependencies(())
    entry_points = await Get(
        PackageJsonEntryPoints, PackageJsonSourceField, request.field_set.source
    )
    candidate_js_files = await Get(Owners, OwnersRequest(tuple(entry_points.globs_from_root())))
    js_targets = await Get(Targets, Addresses(candidate_js_files))
    return InferredDependencies(tgt.address for tgt in js_targets if tgt.has_field(JSSourceField))


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


@dataclass(frozen=True)
class InferenceMetadataRequest:
    imports: PackageJsonImports
    config: TSConfig | None


@rule
async def prepare_inference_metadata(req: InferenceMetadataRequest) -> InferenceMetadata:
    return InferenceMetadata.javascript(
        req.imports.root_dir,
        dict(req.imports.imports),
        req.config.resolution_root_dir if req.config else None,
        dict(req.config.paths or {}) if req.config else {},
    )


async def _prepare_inference_metadata(address: Address, file_path: str) -> InferenceMetadata:
    owning_pkg, maybe_config = await concurrently(
        find_owning_package(OwningNodePackageRequest(address)),
        find_parent_ts_config(ParentTSConfigRequest(file_path, "jsconfig.json"), **implicitly()),
    )
    if not owning_pkg.target:
        return InferenceMetadata.javascript(
            (
                os.path.dirname(maybe_config.ts_config.path)
                if maybe_config.ts_config
                else address.spec_path
            ),
            {},
            maybe_config.ts_config.resolution_root_dir if maybe_config.ts_config else None,
            dict(maybe_config.ts_config.paths or {}) if maybe_config.ts_config else {},
        )
    return await prepare_inference_metadata(
        InferenceMetadataRequest(
            await subpath_imports_for_source(owning_pkg.target[PackageJsonSourceField]),
            maybe_config.ts_config,
        )
    )


@rule
async def infer_js_source_dependencies(
    request: InferJSDependenciesRequest,
    nodejs_infer: NodeJSInfer,
) -> InferredDependencies:
    source: JSSourceField = request.field_set.source
    if not nodejs_infer.imports:
        return InferredDependencies(())

    sources = await Get(
        HydratedSources, HydrateSourcesRequest(source, for_sources_types=[JSSourceField])
    )
    metadata = await _prepare_inference_metadata(request.field_set.address, source.file_path)

    import_strings = await Get(
        NativeParsedJavascriptDependencies,
        NativeDependenciesRequest(sources.snapshot.digest, metadata),
    )
    owners = await Get(Owners, OwnersRequest(tuple(import_strings.file_imports)))
    owning_targets = await Get(Targets, Addresses(owners))

    non_path_string_bases = FrozenOrderedSet(
        non_path_string.partition(os.path.sep)[0]
        for non_path_string in import_strings.package_imports
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
        *tsconfig.rules(),
        UnionRule(InferDependenciesRequest, InferNodePackageDependenciesRequest),
        UnionRule(InferDependenciesRequest, InferJSDependenciesRequest),
    ]
