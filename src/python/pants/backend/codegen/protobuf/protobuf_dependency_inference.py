# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import re
import typing
from collections import defaultdict
from dataclasses import dataclass
from typing import DefaultDict

from pants.backend.codegen.protobuf.protoc import Protoc
from pants.backend.codegen.protobuf.target_types import (
    AllProtobufTargets,
    ProtobufDependenciesField,
    ProtobufSourceField,
    ProtobufSourceTarget,
)
from pants.core.target_types import (
    ResolveLikeField,
    ResolveLikeFieldToValueRequest,
    ResolveLikeFieldToValueResult,
)
from pants.core.util_rules.stripped_source_files import StrippedFileName, StrippedFileNameRequest
from pants.engine.addresses import Address
from pants.engine.fs import Digest, DigestContents
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    DependenciesRequest,
    ExplicitlyProvidedDependencies,
    Field,
    FieldSet,
    HydratedSources,
    HydrateSourcesRequest,
    InferDependenciesRequest,
    InferredDependencies,
    Target,
    WrappedTarget,
    WrappedTargetRequest,
)
from pants.engine.unions import UnionMembership, UnionRule
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.ordered_set import FrozenOrderedSet, OrderedSet
from pants.util.strutil import softwrap


@dataclass(frozen=True)
class ProtobufMappingResolveKey:
    field_type: type[Field]
    resolve: str


_NO_RESOLVE_LIKE_FIELDS_DEFINED = ProtobufMappingResolveKey(
    field_type=ProtobufSourceField, resolve="NONE"
)


@dataclass(frozen=True)
class ProtobufMapping:
    """A mapping of stripped .proto file names to their owning file address indirectly mapped by
    resolve-like fields."""

    mapping: FrozenDict[ProtobufMappingResolveKey, FrozenDict[str, Address]]
    ambiguous_modules: FrozenDict[ProtobufMappingResolveKey, FrozenDict[str, tuple[Address, ...]]]


async def _map_single_pseudo_resolve(protobuf_targets: AllProtobufTargets) -> ProtobufMapping:
    stripped_file_per_target = await MultiGet(
        Get(StrippedFileName, StrippedFileNameRequest(tgt[ProtobufSourceField].file_path))
        for tgt in protobuf_targets
    )

    stripped_files_to_addresses: dict[str, Address] = {}
    stripped_files_with_multiple_owners: DefaultDict[str, set[Address]] = defaultdict(set)
    for tgt, stripped_file in zip(protobuf_targets, stripped_file_per_target):
        if stripped_file.value in stripped_files_to_addresses:
            stripped_files_with_multiple_owners[stripped_file.value].update(
                {stripped_files_to_addresses[stripped_file.value], tgt.address}
            )
        else:
            stripped_files_to_addresses[stripped_file.value] = tgt.address

    # Remove files with ambiguous owners.
    for ambiguous_stripped_f in stripped_files_with_multiple_owners:
        stripped_files_to_addresses.pop(ambiguous_stripped_f)

    return ProtobufMapping(
        mapping=FrozenDict(
            {
                _NO_RESOLVE_LIKE_FIELDS_DEFINED: FrozenDict(
                    sorted(stripped_files_to_addresses.items())
                )
            }
        ),
        ambiguous_modules=FrozenDict(
            {
                _NO_RESOLVE_LIKE_FIELDS_DEFINED: FrozenDict(
                    (k, tuple(sorted(v)))
                    for k, v in sorted(stripped_files_with_multiple_owners.items())
                )
            }
        ),
    )


@rule(desc="Creating map of Protobuf file names to Protobuf targets", level=LogLevel.DEBUG)
async def map_protobuf_files(
    protobuf_targets: AllProtobufTargets, union_membership: UnionMembership
) -> ProtobufMapping:
    # Determine the resolve-like fields installed on the `protobuf_source` target type.
    resolve_like_field_types: set[type[Field]] = set()
    for field_type in ProtobufSourceTarget.class_field_types(union_membership):
        if issubclass(field_type, ResolveLikeField):
            resolve_like_field_types.add(field_type)
    if not resolve_like_field_types:
        return await _map_single_pseudo_resolve(protobuf_targets)

    # Discover which resolves are present in the protobuf_source targets.
    resolve_requests: list[ResolveLikeFieldToValueRequest] = []
    target_and_field_type_for_resolve_requests: list[tuple[Target, type[Field]]] = []
    for tgt in protobuf_targets:
        saw_at_least_one_field = False
        for field_type in resolve_like_field_types:
            if tgt.has_field(field_type):
                resolve_request_type = typing.cast(
                    ResolveLikeField, tgt[field_type]
                ).get_resolve_like_field_to_value_request()
                resolve_request = resolve_request_type(target=tgt)
                resolve_requests.append(resolve_request)
                target_and_field_type_for_resolve_requests.append((tgt, field_type))
                saw_at_least_one_field = True

        if not saw_at_least_one_field:
            raise ValueError(f"Did not find a resolve field on target at address `{tgt.address}`.")

    # Obtain the resolves for each target and then partition.
    resolve_results = await MultiGet(
        Get(ResolveLikeFieldToValueResult, ResolveLikeFieldToValueRequest, resolve_request)
        for resolve_request in resolve_requests
    )
    targets_partitioned_by_resolve: dict[ProtobufMappingResolveKey, list[Target]] = defaultdict(
        list
    )
    for resolve_result, (target, field_type) in zip(
        resolve_results, target_and_field_type_for_resolve_requests
    ):
        resolve_key = ProtobufMappingResolveKey(field_type=field_type, resolve=resolve_result.value)
        targets_partitioned_by_resolve[resolve_key].append(target)

    stripped_file_per_target = await MultiGet(
        Get(StrippedFileName, StrippedFileNameRequest(tgt[ProtobufSourceField].file_path))
        for tgt in protobuf_targets
    )
    target_to_stripped_file: dict[Target, StrippedFileName] = dict(
        zip(protobuf_targets, stripped_file_per_target)
    )

    stripped_files_to_addresses: dict[ProtobufMappingResolveKey, dict[str, Address]] = defaultdict(
        dict
    )
    stripped_files_with_multiple_owners: dict[
        ProtobufMappingResolveKey, dict[str, set[Address]]
    ] = defaultdict(lambda: defaultdict(set))

    for resolve_key, targets_in_resolve in targets_partitioned_by_resolve.items():
        for tgt in targets_in_resolve:
            stripped_file = target_to_stripped_file[tgt]
            if stripped_file.value in stripped_files_to_addresses[resolve_key]:
                stripped_files_with_multiple_owners[resolve_key][stripped_file.value].update(
                    {stripped_files_to_addresses[resolve_key][stripped_file.value], tgt.address}
                )
            else:
                stripped_files_to_addresses[resolve_key][stripped_file.value] = tgt.address

    # Remove files with ambiguous owners in each resolve.
    for (
        resolve_key,
        stripped_files_with_multiple_owners_in_resolve,
    ) in stripped_files_with_multiple_owners.items():
        for ambiguous_stripped_f in stripped_files_with_multiple_owners_in_resolve:
            stripped_files_to_addresses[resolve_key].pop(ambiguous_stripped_f)

    return ProtobufMapping(
        mapping=FrozenDict(
            {
                resolve_key: FrozenDict(sorted(stripped_files_to_addresses_in_resolve.items()))
                for resolve_key, stripped_files_to_addresses_in_resolve in stripped_files_to_addresses.items()
            }
        ),
        ambiguous_modules=FrozenDict(
            {
                resolve_key: FrozenDict(
                    (k, tuple(sorted(v)))
                    for k, v in sorted(stripped_files_with_multiple_owners_in_resolve.items())
                )
                for resolve_key, stripped_files_with_multiple_owners_in_resolve in stripped_files_with_multiple_owners.items()
            }
        ),
    )


# See https://developers.google.com/protocol-buffers/docs/reference/proto3-spec for the Proto
# language spec.
QUOTE_CHAR = r"(?:'|\")"
IMPORT_MODIFIERS = r"(?:\spublic|\sweak)?"
FILE_NAME = r"(.+?\.proto)"
# NB: We don't specify what a valid file name looks like to avoid accidentally breaking unicode.
IMPORT_REGEX = re.compile(rf"import\s*{IMPORT_MODIFIERS}\s*{QUOTE_CHAR}{FILE_NAME}{QUOTE_CHAR}\s*;")


def parse_proto_imports(file_content: str) -> FrozenOrderedSet[str]:
    return FrozenOrderedSet(IMPORT_REGEX.findall(file_content))


@dataclass(frozen=True)
class ProtobufDependencyInferenceFieldSet(FieldSet):
    required_fields = (ProtobufSourceField, ProtobufDependenciesField)

    source: ProtobufSourceField
    dependencies: ProtobufDependenciesField


class InferProtobufDependencies(InferDependenciesRequest):
    infer_from = ProtobufDependencyInferenceFieldSet


async def get_resolve_key_from_target(address: Address) -> ProtobufMappingResolveKey:
    wrapped_target = await Get(
        WrappedTarget, WrappedTargetRequest(address=address, description_of_origin="protobuf")
    )
    resolve_field_type: type[Field] | None = None
    for field_type in wrapped_target.target.field_types:
        if issubclass(field_type, ResolveLikeField):
            if resolve_field_type is not None:
                raise NotImplementedError(
                    f"TODO: Multiple resolve-like fields on target at address `{address}`."
                )
            resolve_field_type = field_type
    if resolve_field_type is None:
        raise ValueError(f"Failed to find resolve-like field on target at address `{address}.")

    resolve_request_type = typing.cast(
        ResolveLikeField, wrapped_target.target[resolve_field_type]
    ).get_resolve_like_field_to_value_request()
    resolve_request = resolve_request_type(target=wrapped_target.target)
    resolve_result = await Get(
        ResolveLikeFieldToValueResult, ResolveLikeFieldToValueRequest, resolve_request
    )

    return ProtobufMappingResolveKey(
        field_type=resolve_field_type,
        resolve=resolve_result.value,
    )


@rule(desc="Inferring Protobuf dependencies by analyzing imports")
async def infer_protobuf_dependencies(
    request: InferProtobufDependencies, protobuf_mapping: ProtobufMapping, protoc: Protoc
) -> InferredDependencies:
    if not protoc.dependency_inference:
        return InferredDependencies([])

    address = request.field_set.address

    resolve_key: ProtobufMappingResolveKey
    if _NO_RESOLVE_LIKE_FIELDS_DEFINED in protobuf_mapping.mapping:
        resolve_key = _NO_RESOLVE_LIKE_FIELDS_DEFINED
    else:
        resolve_key = await get_resolve_key_from_target(address)

    explicitly_provided_deps, hydrated_sources = await MultiGet(
        Get(ExplicitlyProvidedDependencies, DependenciesRequest(request.field_set.dependencies)),
        Get(HydratedSources, HydrateSourcesRequest(request.field_set.source)),
    )
    digest_contents = await Get(DigestContents, Digest, hydrated_sources.snapshot.digest)
    assert len(digest_contents) == 1
    file_content = digest_contents[0]

    result: OrderedSet[Address] = OrderedSet()
    for import_path in parse_proto_imports(file_content.content.decode()):
        mapping_in_resolve = protobuf_mapping.mapping.get(resolve_key)
        unambiguous = mapping_in_resolve.get(import_path) if mapping_in_resolve else None

        ambiguous_modules_in_resolve = protobuf_mapping.ambiguous_modules.get(resolve_key)
        ambiguous = (
            ambiguous_modules_in_resolve.get(import_path) if ambiguous_modules_in_resolve else None
        )

        if unambiguous:
            result.add(unambiguous)
        elif ambiguous:
            explicitly_provided_deps.maybe_warn_of_ambiguous_dependency_inference(
                ambiguous,
                address,
                import_reference="file",
                context=softwrap(
                    f"""
                    The target {address} imports `{import_path}` in the file
                    {file_content.path}
                    """
                ),
            )
            maybe_disambiguated = explicitly_provided_deps.disambiguated(ambiguous)
            if maybe_disambiguated:
                result.add(maybe_disambiguated)
    return InferredDependencies(sorted(result))


def rules():
    return (*collect_rules(), UnionRule(InferDependenciesRequest, InferProtobufDependencies))
