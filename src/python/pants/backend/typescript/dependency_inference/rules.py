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
    RequestNodePackagesCandidateMap,
    _determine_import_from_candidates,
    _handle_unowned_imports,
    _is_node_builtin_module,
    map_candidate_node_packages,
)
from pants.backend.javascript.package_json import (
    OwningNodePackageRequest,
    PackageJsonImports,
    PackageJsonSourceField,
    find_owning_package,
    subpath_imports_for_source,
)
from pants.backend.javascript.subsystems.nodejs_infer import NodeJSInfer
from pants.backend.javascript.target_types import JS_FILE_EXTENSIONS
from pants.backend.tsx.target_types import TSX_FILE_EXTENSIONS
from pants.backend.typescript import tsconfig
from pants.backend.typescript.target_types import (
    TS_FILE_EXTENSIONS,
    TypeScriptDependenciesField,
    TypeScriptSourceField,
)
from pants.backend.typescript.tsconfig import ParentTSConfigRequest, TSConfig, find_parent_ts_config
from pants.build_graph.address import Address
from pants.engine.internals.native_engine import InferenceMetadata, NativeDependenciesRequest
from pants.engine.internals.selectors import Get, concurrently
from pants.engine.intrinsics import parse_javascript_deps
from pants.engine.rules import Rule, collect_rules, implicitly, rule
from pants.engine.target import (
    FieldSet,
    HydratedSources,
    HydrateSourcesRequest,
    InferDependenciesRequest,
    InferredDependencies,
)
from pants.engine.unions import UnionRule


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

    import_strings, candidate_pkgs = await concurrently(
        parse_javascript_deps(NativeDependenciesRequest(sources.snapshot.digest, metadata)),
        map_candidate_node_packages(
            RequestNodePackagesCandidateMap(request.field_set.address), **implicitly()
        ),
    )

    imports = dict(
        zip(
            import_strings.imports,
            await concurrently(
                _determine_import_from_candidates(
                    candidates,
                    candidate_pkgs,
                    file_extensions=TS_FILE_EXTENSIONS + TSX_FILE_EXTENSIONS + JS_FILE_EXTENSIONS,
                )
                for string, candidates in import_strings.imports.items()
            ),
        )
    )
    _handle_unowned_imports(
        request.field_set.address,
        nodejs_infer.unowned_dependency_behavior,
        frozenset(
            string
            for string, addresses in imports.items()
            if not addresses and not _is_node_builtin_module(string)
        ),
    )
    return InferredDependencies(itertools.chain.from_iterable(imports.values()))


def rules() -> Iterable[Rule | UnionRule]:
    return [
        *collect_rules(),
        *package_json.rules(),
        *tsconfig.rules(),
        UnionRule(InferDependenciesRequest, InferNodePackageDependenciesRequest),
        UnionRule(InferDependenciesRequest, InferTypeScriptDependenciesRequest),
    ]
