# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import contextlib
import json
import os.path
from dataclasses import dataclass
from typing import Any, Mapping

import yaml

from pants.backend.openapi.target_types import OpenApiDefinitionField, OpenApiSourceField
from pants.base.glob_match_error_behavior import GlobMatchErrorBehavior
from pants.base.specs import FileLiteralSpec, RawSpecs
from pants.engine.fs import Digest, DigestContents
from pants.engine.internals.selectors import Get
from pants.engine.rules import collect_rules, rule
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
        elif digest_content.path.endswith(".yaml"):
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
            v = v.split("#", 1)[0]

            if (v.endswith(".json") or v.endswith(".yaml")) and "://" not in v:
                normalized = os.path.normpath(os.path.join(os.path.dirname(path), v))

                if not normalized.startswith("../"):
                    local_refs.add(normalized)

    return frozenset(local_refs)


# -----------------------------------------------------------------------------------------------
# `openapi_definition` dependency inference
# -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class OpenApiDefinitionDependenciesInferenceFieldSet(FieldSet):
    required_fields = (OpenApiDefinitionField,)

    sources: OpenApiDefinitionField


class InferOpenApiDefinitionDependenciesRequest(InferDependenciesRequest):
    infer_from = OpenApiDefinitionDependenciesInferenceFieldSet


@rule
async def infer_openapi_definition_dependencies(
    request: InferOpenApiDefinitionDependenciesRequest,
) -> InferredDependencies:
    hydrated_sources = await Get(HydratedSources, HydrateSourcesRequest(request.field_set.sources))
    candidate_targets = await Get(
        Targets,
        RawSpecs(
            file_literals=(FileLiteralSpec(*hydrated_sources.snapshot.files),),
            description_of_origin="the `openapi_definition` dependency inference",
        ),
    )

    addresses = [
        target.address for target in candidate_targets if target.has_field(OpenApiSourceField)
    ]

    return InferredDependencies(addresses)


# -----------------------------------------------------------------------------------------------
# `openapi_source` dependency inference
# -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class OpenApiSourceDependenciesInferenceFieldSet(FieldSet):
    required_fields = (OpenApiSourceField,)

    sources: OpenApiSourceField


class InferOpenApiSourceDependenciesRequest(InferDependenciesRequest):
    infer_from = OpenApiSourceDependenciesInferenceFieldSet


@rule
async def infer_openapi_module_dependencies(
    request: InferOpenApiSourceDependenciesRequest,
) -> InferredDependencies:
    hydrated_sources = await Get(HydratedSources, HydrateSourcesRequest(request.field_set.sources))
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

    addresses = [
        target.address for target in candidate_targets if target.has_field(OpenApiSourceField)
    ]

    return InferredDependencies(addresses)


def rules():
    return [
        *collect_rules(),
        UnionRule(InferDependenciesRequest, InferOpenApiDefinitionDependenciesRequest),
        UnionRule(InferDependenciesRequest, InferOpenApiSourceDependenciesRequest),
    ]
