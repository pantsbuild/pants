# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import re
from typing import Dict, Set

from pants.backend.codegen.protobuf.protoc import Protoc
from pants.backend.codegen.protobuf.target_types import ProtobufSources
from pants.base.specs import AddressSpecs, DescendantAddresses
from pants.core.util_rules.stripped_source_files import StrippedSourceFileNames
from pants.engine.addresses import Address
from pants.engine.fs import Digest, DigestContents
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    HydratedSources,
    HydrateSourcesRequest,
    InferDependenciesRequest,
    InferredDependencies,
    SourcesPathsRequest,
    Targets,
)
from pants.engine.unions import UnionRule
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.ordered_set import FrozenOrderedSet


class ProtobufMapping(FrozenDict[str, Address]):
    """A mapping of stripped .proto file names to their owning file address."""


@rule(desc="Creating map of Protobuf file names to Protobuf targets", level=LogLevel.DEBUG)
async def map_protobuf_files() -> ProtobufMapping:
    all_expanded_targets = await Get(Targets, AddressSpecs([DescendantAddresses("")]))
    protobuf_targets = tuple(tgt for tgt in all_expanded_targets if tgt.has_field(ProtobufSources))
    stripped_sources_per_target = await MultiGet(
        Get(StrippedSourceFileNames, SourcesPathsRequest(tgt[ProtobufSources]))
        for tgt in protobuf_targets
    )

    stripped_files_to_addresses: Dict[str, Address] = {}
    stripped_files_with_multiple_owners: Set[str] = set()
    for tgt, stripped_sources in zip(protobuf_targets, stripped_sources_per_target):
        for stripped_f in stripped_sources:
            if stripped_f in stripped_files_to_addresses:
                stripped_files_with_multiple_owners.add(stripped_f)
            else:
                stripped_files_to_addresses[stripped_f] = tgt.address

    # Remove files with ambiguous owners.
    for ambiguous_stripped_f in stripped_files_with_multiple_owners:
        stripped_files_to_addresses.pop(ambiguous_stripped_f)

    return ProtobufMapping(stripped_files_to_addresses)


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
    infer_from = ProtobufSources


@rule(desc="Inferring Protobuf dependencies by analyzing imports")
async def infer_protobuf_dependencies(
    request: InferProtobufDependencies, protobuf_mapping: ProtobufMapping, protoc: Protoc
) -> InferredDependencies:
    if not protoc.dependency_inference:
        return InferredDependencies([], sibling_dependencies_inferrable=False)

    hydrated_sources = await Get(HydratedSources, HydrateSourcesRequest(request.sources_field))
    digest_contents = await Get(DigestContents, Digest, hydrated_sources.snapshot.digest)
    result = sorted(
        {
            protobuf_mapping[import_path]
            for file_content in digest_contents
            for import_path in parse_proto_imports(file_content.content.decode())
            if import_path in protobuf_mapping
        }
    )
    return InferredDependencies(result, sibling_dependencies_inferrable=True)


def rules():
    return (*collect_rules(), UnionRule(InferDependenciesRequest, InferProtobufDependencies))
