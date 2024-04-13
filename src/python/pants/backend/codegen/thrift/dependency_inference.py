# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import DefaultDict

from pants.backend.codegen.thrift import thrift_parser
from pants.backend.codegen.thrift.subsystem import ThriftSubsystem
from pants.backend.codegen.thrift.target_types import (
    AllThriftTargets,
    ThriftDependenciesField,
    ThriftSourceField,
)
from pants.backend.codegen.thrift.thrift_parser import ParsedThrift, ParsedThriftRequest
from pants.core.util_rules.stripped_source_files import StrippedFileName, StrippedFileNameRequest
from pants.engine.addresses import Address
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    DependenciesRequest,
    ExplicitlyProvidedDependencies,
    FieldSet,
    InferDependenciesRequest,
    InferredDependencies,
)
from pants.engine.unions import UnionRule
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.ordered_set import OrderedSet
from pants.util.strutil import softwrap


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


@dataclass(frozen=True)
class ThriftDependenciesInferenceFieldSet(FieldSet):
    required_fields = (ThriftSourceField, ThriftDependenciesField)

    source: ThriftSourceField
    dependencies: ThriftDependenciesField


class InferThriftDependencies(InferDependenciesRequest):
    infer_from = ThriftDependenciesInferenceFieldSet


@rule(desc="Inferring Thrift dependencies by analyzing imports")
async def infer_thrift_dependencies(
    request: InferThriftDependencies, thrift_mapping: ThriftMapping, thrift: ThriftSubsystem
) -> InferredDependencies:
    if not thrift.dependency_inference:
        return InferredDependencies([])

    address = request.field_set.address
    explicitly_provided_deps, parsed_thrift = await MultiGet(
        Get(ExplicitlyProvidedDependencies, DependenciesRequest(request.field_set.dependencies)),
        Get(ParsedThrift, ParsedThriftRequest(request.field_set.source)),
    )

    result: OrderedSet[Address] = OrderedSet()
    for import_path in parsed_thrift.imports:
        unambiguous = thrift_mapping.mapping.get(import_path)
        ambiguous = thrift_mapping.ambiguous_modules.get(import_path)
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
                    {request.field_set.source.file_path}
                    """
                ),
            )
            maybe_disambiguated = explicitly_provided_deps.disambiguated(ambiguous)
            if maybe_disambiguated:
                result.add(maybe_disambiguated)
    return InferredDependencies(sorted(result))


def rules():
    return (
        *collect_rules(),
        *thrift_parser.rules(),
        UnionRule(InferDependenciesRequest, InferThriftDependencies),
    )
