# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import DefaultDict

from pants.backend.codegen.thrift.subsystem import ThriftSubsystem
from pants.backend.codegen.thrift.target_types import AllThriftTargets, ThriftSourceField
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
class ThriftMapping:
    """A mapping of stripped .thrift file names to their owning file address."""

    mapping: FrozenDict[str, Address]
    ambiguous_modules: FrozenDict[str, tuple[Address, ...]]


@rule(desc="Creating map of Thrift file names to Thrift targets", level=LogLevel.DEBUG)
async def map_thrift_files(thrift_targets: AllThriftTargets) -> ThriftMapping:
    stripped_file_per_target = await MultiGet(
        Get(StrippedFileName, StrippedFileNameRequest(tgt[ThriftSourceField].file_path))
        for tgt in thrift_targets
    )

    stripped_files_to_addresses: dict[str, Address] = {}
    stripped_files_with_multiple_owners: DefaultDict[str, set[Address]] = defaultdict(set)
    for tgt, stripped_file in zip(thrift_targets, stripped_file_per_target):
        if stripped_file.value in stripped_files_to_addresses:
            stripped_files_with_multiple_owners[stripped_file.value].update(
                {stripped_files_to_addresses[stripped_file.value], tgt.address}
            )
        else:
            stripped_files_to_addresses[stripped_file.value] = tgt.address

    # Remove files with ambiguous owners.
    for ambiguous_stripped_f in stripped_files_with_multiple_owners:
        stripped_files_to_addresses.pop(ambiguous_stripped_f)

    return ThriftMapping(
        mapping=FrozenDict(sorted(stripped_files_to_addresses.items())),
        ambiguous_modules=FrozenDict(
            (k, tuple(sorted(v))) for k, v in sorted(stripped_files_with_multiple_owners.items())
        ),
    )


QUOTE_CHAR = r"(?:'|\")"
FILE_NAME = r"(.+?\.thrift)"
# NB: We don't specify what a valid file name looks like to avoid accidentally breaking unicode.
IMPORT_REGEX = re.compile(rf"include\s*{QUOTE_CHAR}{FILE_NAME}{QUOTE_CHAR}\s*")


def parse_thrift_imports(file_content: str) -> FrozenOrderedSet[str]:
    return FrozenOrderedSet(IMPORT_REGEX.findall(file_content))


class InferThriftDependencies(InferDependenciesRequest):
    infer_from = ThriftSourceField


@rule(desc="Inferring Thrift dependencies by analyzing imports")
async def infer_thrift_dependencies(
    request: InferThriftDependencies, thrift_mapping: ThriftMapping, thrift: ThriftSubsystem
) -> InferredDependencies:
    if not thrift.dependency_inference:
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
    for import_path in parse_thrift_imports(file_content.content.decode()):
        unambiguous = thrift_mapping.mapping.get(import_path)
        ambiguous = thrift_mapping.ambiguous_modules.get(import_path)
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
    return (*collect_rules(), UnionRule(InferDependenciesRequest, InferThriftDependencies))
