# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import DefaultDict

from pants.backend.codegen.protobuf.protoc import Protoc
from pants.backend.codegen.protobuf.target_types import AllProtobufTargets, ProtobufSourceField
from pants.core.util_rules.stripped_source_files import StrippedFileName, StrippedFileNameRequest
from pants.engine.addresses import Address
from pants.engine.fs import Digest, DigestContents
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    Dependencies,
    DependenciesRequest,
    ExplicitlyProvidedDependencies,
    HydratedSources,
    HydrateSourcesRequest,
    InferDependenciesRequest,
    InferredDependencies,
    WrappedTarget,
)
from pants.engine.unions import UnionRule
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.ordered_set import FrozenOrderedSet, OrderedSet


@dataclass(frozen=True)
class ProtobufMapping:
    """A mapping of stripped .proto file names to their owning file address."""

    mapping: FrozenDict[str, Address]
    ambiguous_modules: FrozenDict[str, tuple[Address, ...]]


@rule(desc="Creating map of Protobuf file names to Protobuf targets", level=LogLevel.DEBUG)
async def map_protobuf_files(protobuf_targets: AllProtobufTargets) -> ProtobufMapping:
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
        mapping=FrozenDict(sorted(stripped_files_to_addresses.items())),
        ambiguous_modules=FrozenDict(
            (k, tuple(sorted(v))) for k, v in sorted(stripped_files_with_multiple_owners.items())
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


class InferProtobufDependencies(InferDependenciesRequest):
    infer_from = ProtobufSourceField


@rule(desc="Inferring Protobuf dependencies by analyzing imports")
async def infer_protobuf_dependencies(
    request: InferProtobufDependencies, protobuf_mapping: ProtobufMapping, protoc: Protoc
) -> InferredDependencies:
    if not protoc.dependency_inference:
        return InferredDependencies([])

    address = request.sources_field.address
    wrapped_tgt = await Get(WrappedTarget, Address, address)
    explicitly_provided_deps, hydrated_sources = await MultiGet(
        Get(ExplicitlyProvidedDependencies, DependenciesRequest(wrapped_tgt.target[Dependencies])),
        Get(HydratedSources, HydrateSourcesRequest(request.sources_field)),
    )
    digest_contents = await Get(DigestContents, Digest, hydrated_sources.snapshot.digest)
    assert len(digest_contents) == 1
    file_content = digest_contents[0]

    result: OrderedSet[Address] = OrderedSet()
    for import_path in parse_proto_imports(file_content.content.decode()):
        unambiguous = protobuf_mapping.mapping.get(import_path)
        ambiguous = protobuf_mapping.ambiguous_modules.get(import_path)
        if unambiguous:
            result.add(unambiguous)
        elif ambiguous:
            explicitly_provided_deps.maybe_warn_of_ambiguous_dependency_inference(
                ambiguous,
                address,
                import_reference="file",
                context=(
                    f"The target {address} imports `{import_path}` in the file "
                    f"{file_content.path}"
                ),
            )
            maybe_disambiguated = explicitly_provided_deps.disambiguated(ambiguous)
            if maybe_disambiguated:
                result.add(maybe_disambiguated)
    return InferredDependencies(sorted(result))


def rules():
    return (*collect_rules(), UnionRule(InferDependenciesRequest, InferProtobufDependencies))
