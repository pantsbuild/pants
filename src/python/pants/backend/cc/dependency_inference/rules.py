# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import PurePath
from typing import DefaultDict

from pants.backend.cc.subsystems.cc_infer import CCInferSubsystem
from pants.backend.cc.target_types import CCSourceField
from pants.build_graph.address import Address
from pants.core.util_rules import stripped_source_files
from pants.core.util_rules.stripped_source_files import StrippedFileName, StrippedFileNameRequest
from pants.engine.fs import DigestContents
from pants.engine.internals.native_engine import Digest
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import collect_rules, rule
from pants.engine.target import (
    AllTargets,
    Dependencies,
    DependenciesRequest,
    ExplicitlyProvidedDependencies,
    HydratedSources,
    HydrateSourcesRequest,
    InferDependenciesRequest,
    InferredDependencies,
    Targets,
    WrappedTarget,
    WrappedTargetRequest,
)
from pants.engine.unions import UnionRule
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.ordered_set import OrderedSet
from pants.util.strutil import softwrap

INCLUDE_REGEX = re.compile(r"^\s*#\s*include\s+((\".*\")|(<.*>))")


class InferCCDependenciesRequest(InferDependenciesRequest):
    infer_from = CCSourceField


class AllCCTargets(Targets):
    pass


@rule(desc="Find all CC targets in project", level=LogLevel.DEBUG)
def find_all_cc_targets(targets: AllTargets) -> AllCCTargets:
    return AllCCTargets(tgt for tgt in targets if tgt.has_field(CCSourceField))


@dataclass(frozen=True)
class CCFilesMapping:
    """A mapping of stripped CC file names to their owning file address."""

    mapping: FrozenDict[str, Address]
    ambiguous_files: FrozenDict[str, tuple[Address, ...]]
    mapping_not_stripped: FrozenDict[str, Address]


@rule(desc="Creating map of CC file names to CC targets", level=LogLevel.DEBUG)
async def map_cc_files(cc_targets: AllCCTargets) -> CCFilesMapping:
    stripped_file_per_target = await MultiGet(
        Get(StrippedFileName, StrippedFileNameRequest(tgt[CCSourceField].file_path))
        for tgt in cc_targets
    )

    stripped_files_to_addresses: dict[str, Address] = {}
    stripped_files_with_multiple_owners: DefaultDict[str, set[Address]] = defaultdict(set)
    for tgt, stripped_file in zip(cc_targets, stripped_file_per_target):
        if stripped_file.value in stripped_files_to_addresses:
            stripped_files_with_multiple_owners[stripped_file.value].update(
                {stripped_files_to_addresses[stripped_file.value], tgt.address}
            )
        else:
            stripped_files_to_addresses[stripped_file.value] = tgt.address

    # Remove files with ambiguous owners.
    for ambiguous_stripped_f in stripped_files_with_multiple_owners:
        stripped_files_to_addresses.pop(ambiguous_stripped_f)

    mapping_not_stripped = {tgt[CCSourceField].file_path: tgt.address for tgt in cc_targets}

    return CCFilesMapping(
        mapping=FrozenDict(sorted(stripped_files_to_addresses.items())),
        ambiguous_files=FrozenDict(
            (k, tuple(sorted(v))) for k, v in sorted(stripped_files_with_multiple_owners.items())
        ),
        mapping_not_stripped=FrozenDict(mapping_not_stripped),
    )


@dataclass(frozen=True)
class CCIncludeDirective:
    path: str
    system_paths_only: bool  # True if include used `<foo.h>` instead of `"foo.h"`.


def parse_includes(content: str) -> frozenset[CCIncludeDirective]:
    includes: set[CCIncludeDirective] = set()
    for line in content.splitlines():
        m = INCLUDE_REGEX.match(line)
        if m:
            if m.group(2):
                includes.add(CCIncludeDirective(m.group(2)[1:-1], False))
            elif m.group(3):
                includes.add(CCIncludeDirective(m.group(3)[1:-1], True))
    return frozenset(includes)


@rule
async def infer_cc_source_dependencies(
    request: InferCCDependenciesRequest,
    cc_files_mapping: CCFilesMapping,
    cc_infer: CCInferSubsystem,
) -> InferredDependencies:
    if not cc_infer.includes:
        return InferredDependencies([])

    address = request.sources_field.address
    wrapped_tgt = await Get(
        WrappedTarget, WrappedTargetRequest(address, description_of_origin="<infallible>")
    )
    explicitly_provided_deps, hydrated_sources = await MultiGet(
        Get(ExplicitlyProvidedDependencies, DependenciesRequest(wrapped_tgt.target[Dependencies])),
        Get(HydratedSources, HydrateSourcesRequest(request.sources_field)),
    )

    digest_contents = await Get(DigestContents, Digest, hydrated_sources.snapshot.digest)
    assert len(digest_contents) == 1
    file_content = digest_contents[0]
    file_path = PurePath(file_content.path)

    includes = parse_includes(file_content.content.decode())

    result: OrderedSet[Address] = OrderedSet()
    for include in includes:
        # Skip system-path includes.
        if include.system_paths_only:
            continue

        # First try to resolve the include's path against the same directory where the file is.
        maybe_relative_file_path = file_path.parent.joinpath(include.path)
        maybe_relative_address = cc_files_mapping.mapping_not_stripped.get(
            str(maybe_relative_file_path)
        )
        if maybe_relative_address:
            result.add(maybe_relative_address)
            continue

        # Otherwise try source roots.
        if cc_infer.include_from_source_roots:
            unambiguous = cc_files_mapping.mapping.get(include.path)
            ambiguous = cc_files_mapping.ambiguous_files.get(include.path)
            if unambiguous:
                result.add(unambiguous)
            elif ambiguous:
                explicitly_provided_deps.maybe_warn_of_ambiguous_dependency_inference(
                    ambiguous,
                    address,
                    import_reference="file",
                    context=softwrap(
                        f"""
                        The target {address} includes `{include.path}` in the file
                        {file_content.path}
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
        *stripped_source_files.rules(),
        UnionRule(InferDependenciesRequest, InferCCDependenciesRequest),
    )
