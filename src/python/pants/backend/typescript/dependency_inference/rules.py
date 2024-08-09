# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import itertools
import os.path
from dataclasses import dataclass
from typing import Iterable

from pants.backend.javascript import package_json
from pants.backend.javascript.dependency_inference.rules import (
    InferNodePackageDependenciesRequest,
    NodePackageCandidateMap,
    RequestNodePackagesCandidateMap,
)
from pants.backend.javascript.package_json import (
    OwningNodePackageRequest,
    PackageJsonImports,
    PackageJsonSourceField,
    find_owning_package,
    subpath_imports_for_source,
)
from pants.backend.javascript.subsystems.nodejs_infer import NodeJSInfer
from pants.backend.typescript import tsconfig
from pants.backend.typescript.target_types import (
    TS_FILE_EXTENSIONS,
    TypeScriptDependenciesField,
    TypeScriptSourceField,
)
from pants.backend.typescript.tsconfig import ParentTSConfigRequest, TSConfig, find_parent_ts_config
from pants.build_graph.address import Address
from pants.engine.addresses import Addresses
from pants.engine.internals.graph import Owners, OwnersRequest
from pants.engine.internals.native_dep_inference import NativeParsedJavascriptDependencies
from pants.engine.internals.native_engine import InferenceMetadata, NativeDependenciesRequest
from pants.engine.internals.selectors import Get, MultiGet, concurrently
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
from pants.util.ordered_set import FrozenOrderedSet


@dataclass(frozen=True)
class TypeScriptSourceInferenceFieldSet(FieldSet):
    required_fields = (TypeScriptSourceField, TypeScriptDependenciesField)

    source: TypeScriptSourceField
    dependencies: TypeScriptDependenciesField


@dataclass(frozen=True)
class TypeScriptFileImportPath:
    """Path to a file that is imported in TypeScript code."""

    path: str


class InferTypeScriptDependenciesRequest(InferDependenciesRequest):
    infer_from = TypeScriptSourceInferenceFieldSet


def _create_inference_metadata(
    imports: PackageJsonImports, config: TSConfig | None
) -> InferenceMetadata:
    return InferenceMetadata.javascript(
        imports.root_dir,
        dict(imports.imports),
        config.resolution_root_dir if config else None,
        dict(config.paths or {}) if config else {},
    )


async def _prepare_inference_metadata(address: Address, file_path: str) -> InferenceMetadata:
    owning_pkg, maybe_config = await concurrently(
        find_owning_package(OwningNodePackageRequest(address)),
        find_parent_ts_config(ParentTSConfigRequest(file_path, "tsconfig.json"), **implicitly()),
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
    return _create_inference_metadata(
        await subpath_imports_for_source(owning_pkg.target[PackageJsonSourceField]),
        maybe_config.ts_config,
    )


@rule
async def get_file_imports_targets(import_path: TypeScriptFileImportPath) -> Targets:
    """Get address to build targets representing a file import discovered with dependency inference.

    For now, we only support .ts files; in the future, may need to iterate through all possible file
    extensions until find one matching, if any.
    """
    package, filename = os.path.dirname(import_path.path), os.path.basename(import_path.path)
    address = Address(package, relative_file_path=f"{filename}{TS_FILE_EXTENSIONS[0]}")
    _ = await Get(Targets, Addresses([address]))
    owners = await Get(Owners, OwnersRequest((str(address),)))
    owning_targets = await Get(Targets, Addresses(owners))
    return owning_targets


@rule
async def infer_typescript_source_dependencies(
    request: InferTypeScriptDependenciesRequest,
    nodejs_infer: NodeJSInfer,
) -> InferredDependencies:
    source: TypeScriptSourceField = request.field_set.source
    if not nodejs_infer.imports:
        return InferredDependencies(())

    sources = await Get(
        HydratedSources, HydrateSourcesRequest(source, for_sources_types=[TypeScriptSourceField])
    )
    metadata = await _prepare_inference_metadata(request.field_set.address, source.file_path)

    import_strings = await Get(
        NativeParsedJavascriptDependencies,
        NativeDependenciesRequest(sources.snapshot.digest, metadata),
    )

    owning_targets_collection = await MultiGet(
        Get(Targets, TypeScriptFileImportPath, TypeScriptFileImportPath(path=path))
        for path in import_strings.file_imports
    )
    owning_targets = [tgt for targets in owning_targets_collection for tgt in targets]

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
            (tgt.address for tgt in owning_targets if tgt.has_field(TypeScriptSourceField)),
        )
    )


def rules() -> Iterable[Rule | UnionRule]:
    return [
        *collect_rules(),
        *package_json.rules(),
        *tsconfig.rules(),
        UnionRule(InferDependenciesRequest, InferNodePackageDependenciesRequest),
        UnionRule(InferDependenciesRequest, InferTypeScriptDependenciesRequest),
    ]
