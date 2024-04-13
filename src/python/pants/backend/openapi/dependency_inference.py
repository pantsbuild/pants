# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import contextlib
import json
import os.path
from dataclasses import dataclass
from typing import Any, Mapping

import yaml

from pants.backend.openapi.target_types import (
    OPENAPI_FILE_EXTENSIONS,
    OpenApiDocumentDependenciesField,
    OpenApiDocumentField,
    OpenApiSourceDependenciesField,
    OpenApiSourceField,
)
from pants.base.glob_match_error_behavior import GlobMatchErrorBehavior
from pants.base.specs import FileLiteralSpec, RawSpecs
from pants.engine.fs import Digest, DigestContents
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import collect_rules, rule
from pants.engine.target import (
    DependenciesRequest,
    ExplicitlyProvidedDependencies,
    FieldSet,
    HydratedSources,
    HydrateSourcesRequest,
    InferDependenciesRequest,
    InferredDependencies,
    Targets,
)
from pants.engine.unions import UnionRule
from pants.util.frozendict import FrozenDict


@dataclass(frozen=True)
class ParseOpenApiSources:
    sources_digest: Digest
    paths: tuple[str, ...]


@dataclass(frozen=True)
class OpenApiDependencies:
    dependencies: FrozenDict[str, frozenset[str]]


@rule
async def parse_openapi_sources(request: ParseOpenApiSources) -> OpenApiDependencies:
    digest_contents = await Get(DigestContents, Digest, request.sources_digest)
    dependencies: dict[str, frozenset[str]] = {}

    for digest_content in digest_contents:
        spec = None

        if digest_content.path.endswith(".json"):
            with contextlib.suppress(json.JSONDecodeError):
                spec = json.loads(digest_content.content)
        elif digest_content.path.endswith(".yaml") or digest_content.path.endswith(".yml"):
            with contextlib.suppress(yaml.YAMLError):
                spec = yaml.safe_load(digest_content.content)

        if not spec or not isinstance(spec, dict):
            dependencies[digest_content.path] = frozenset()
            continue

        dependencies[digest_content.path] = _find_local_refs(digest_content.path, spec)

    return OpenApiDependencies(dependencies=FrozenDict(dependencies))


def _find_local_refs(path: str, d: Mapping[str, Any]) -> frozenset[str]:
    local_refs: set[str] = set()

    for k, v in d.items():
        if isinstance(v, dict):
            local_refs.update(_find_local_refs(path, v))
        elif k == "$ref" and isinstance(v, str):
            # https://swagger.io/specification/#reference-object
            # https://datatracker.ietf.org/doc/html/draft-pbryan-zyp-json-ref-03
            v = v.split("#", 1)[0]

            if any(v.endswith(ext) for ext in OPENAPI_FILE_EXTENSIONS) and "://" not in v:
                # Resolution is performed relative to the referring document.
                normalized = os.path.normpath(os.path.join(os.path.dirname(path), v))

                if not normalized.startswith("../"):
                    local_refs.add(normalized)

    return frozenset(local_refs)


# -----------------------------------------------------------------------------------------------
# `openapi_document` dependency inference
# -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class OpenApiDocumentDependenciesInferenceFieldSet(FieldSet):
    required_fields = (OpenApiDocumentField, OpenApiDocumentDependenciesField)

    sources: OpenApiDocumentField
    dependencies: OpenApiDocumentDependenciesField


class InferOpenApiDocumentDependenciesRequest(InferDependenciesRequest):
    infer_from = OpenApiDocumentDependenciesInferenceFieldSet


@rule
async def infer_openapi_document_dependencies(
    request: InferOpenApiDocumentDependenciesRequest,
) -> InferredDependencies:
    explicitly_provided_deps, hydrated_sources = await MultiGet(
        Get(ExplicitlyProvidedDependencies, DependenciesRequest(request.field_set.dependencies)),
        Get(HydratedSources, HydrateSourcesRequest(request.field_set.sources)),
    )
    candidate_targets = await Get(
        Targets,
        RawSpecs(
            file_literals=(FileLiteralSpec(*hydrated_sources.snapshot.files),),
            description_of_origin="the `openapi_document` dependency inference",
        ),
    )

    addresses = frozenset(
        [target.address for target in candidate_targets if target.has_field(OpenApiSourceField)]
    )
    dependencies = explicitly_provided_deps.remaining_after_disambiguation(
        addresses.union(explicitly_provided_deps.includes),
        owners_must_be_ancestors=False,
    )

    return InferredDependencies(dependencies)


# -----------------------------------------------------------------------------------------------
# `openapi_source` dependency inference
# -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class OpenApiSourceDependenciesInferenceFieldSet(FieldSet):
    required_fields = (OpenApiSourceField, OpenApiSourceDependenciesField)

    sources: OpenApiSourceField
    dependencies: OpenApiSourceDependenciesField


class InferOpenApiSourceDependenciesRequest(InferDependenciesRequest):
    infer_from = OpenApiSourceDependenciesInferenceFieldSet


@rule
async def infer_openapi_module_dependencies(
    request: InferOpenApiSourceDependenciesRequest,
) -> InferredDependencies:
    explicitly_provided_deps, hydrated_sources = await MultiGet(
        Get(ExplicitlyProvidedDependencies, DependenciesRequest(request.field_set.dependencies)),
        Get(HydratedSources, HydrateSourcesRequest(request.field_set.sources)),
    )
    result = await Get(
        OpenApiDependencies,
        ParseOpenApiSources(
            sources_digest=hydrated_sources.snapshot.digest,
            paths=hydrated_sources.snapshot.files,
        ),
    )

    paths: set[str] = set()

    for source_file in hydrated_sources.snapshot.files:
        paths.update(result.dependencies[source_file])

    candidate_targets = await Get(
        Targets,
        RawSpecs(
            file_literals=tuple(FileLiteralSpec(path) for path in paths),
            unmatched_glob_behavior=GlobMatchErrorBehavior.ignore,
            description_of_origin="the `openapi_source` dependency inference",
        ),
    )

    addresses = frozenset(
        [target.address for target in candidate_targets if target.has_field(OpenApiSourceField)]
    )
    dependencies = explicitly_provided_deps.remaining_after_disambiguation(
        addresses.union(explicitly_provided_deps.includes),
        owners_must_be_ancestors=False,
    )

    return InferredDependencies(dependencies)


def rules():
    return [
        *collect_rules(),
        UnionRule(InferDependenciesRequest, InferOpenApiDocumentDependenciesRequest),
        UnionRule(InferDependenciesRequest, InferOpenApiSourceDependenciesRequest),
    ]
