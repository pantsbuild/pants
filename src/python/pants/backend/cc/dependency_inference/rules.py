# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import logging
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import PurePath
from typing import DefaultDict, Iterable

from pants.backend.cc.subsystems.cc_infer import CCInferSubsystem
from pants.backend.cc.target_types import CCDependenciesField, CCSourceField
from pants.build_graph.address import Address
from pants.core.util_rules import stripped_source_files
from pants.core.util_rules.stripped_source_files import StrippedFileName, StrippedFileNameRequest
from pants.engine.fs import DigestContents
from pants.engine.internals.native_engine import Digest
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import collect_rules, rule, rule_helper
from pants.engine.target import (
    AllTargets,
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
from pants.source.source_root import SourceRoot, SourceRootsRequest, SourceRootsResult
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.ordered_set import OrderedSet
from pants.util.strutil import softwrap

INCLUDE_REGEX = re.compile(r"^\s*#\s*include\s+((\".*\")|(<.*>))")

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CCDependencyInferenceFieldSet(FieldSet):
    required_fields = (CCSourceField, CCDependenciesField)

    sources: CCSourceField
    dependencies: CCDependenciesField


class InferCCDependenciesRequest(InferDependenciesRequest):
    infer_from = CCDependencyInferenceFieldSet


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
    alternative_source_roots: FrozenDict[str, Address]


@rule_helper
async def _header_(
    cc_file_mapping: dict[str, Address], include_dir_names: Iterable[str] = tuple("include")
) -> dict[str, Address]:
    # Get unique source roots for all CC source fields
    paths: set[PurePath] = set()
    for source_file_path in cc_file_mapping.keys():
        paths = paths.union(PurePath(source_file_path).parents)

    source_roots_result = await Get(SourceRootsResult, SourceRootsRequest([], paths))
    source_roots = set(source_roots_result.path_to_root.values())
    source_roots.remove(SourceRoot(path="."))

    alternative_source_roots: dict[str, Address] = {}

    # Determine if there is a source root in the file's path, and create an alternative mapping with those roots
    # This is particularly useful to discover if there are include directories that need to be passed to compiler
    for file_path, address in cc_file_mapping.items():
        for source_root in source_roots:
            include_path = next(
                (
                    path
                    for name in include_dir_names
                    if (path := f"{source_root.path}/{name}/") in file_path
                ),
                "",
            )
            if include_path:
                stripped_path = file_path.replace(include_path, "")
                alternative_source_roots[stripped_path] = address

    return alternative_source_roots


@rule(desc="Creating map of CC file names to CC targets", level=LogLevel.DEBUG)
async def map_cc_files(cc_targets: AllCCTargets, cc_infer: CCInferSubsystem) -> CCFilesMapping:
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

    alternative_source_roots = await _header_(
        mapping_not_stripped, tuple(cc_infer.include_dir_names)
    )

    return CCFilesMapping(
        mapping=FrozenDict(sorted(stripped_files_to_addresses.items())),
        ambiguous_files=FrozenDict(
            (k, tuple(sorted(v))) for k, v in sorted(stripped_files_with_multiple_owners.items())
        ),
        mapping_not_stripped=FrozenDict(mapping_not_stripped),
        alternative_source_roots=FrozenDict(alternative_source_roots),
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

    address = request.field_set.address
    explicitly_provided_deps, hydrated_sources = await MultiGet(
        Get(ExplicitlyProvidedDependencies, DependenciesRequest(request.field_set.dependencies)),
        Get(HydratedSources, HydrateSourcesRequest(request.field_set.sources)),
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
            logger.warning(f"Maybe: {maybe_relative_address}")
            continue

        # Otherwise try source roots.
        if cc_infer.include_from_source_roots:
            unambiguous = cc_files_mapping.mapping.get(include.path)
            ambiguous = cc_files_mapping.ambiguous_files.get(include.path)
            if unambiguous:
                result.add(unambiguous)
                logger.info("Unambiguous --- continuing")
                continue

            if ambiguous:
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
                    continue

        # Finally, check the alternative source roots
        logger.debug(f"Checking alternatives for {include.path}")
        alternative = cc_files_mapping.alternative_source_roots.get(include.path)
        if alternative:
            result.add(alternative)

    logger.warning(f"Results: {result}")
    return InferredDependencies(sorted(result))


def rules():
    return (
        *collect_rules(),
        *stripped_source_files.rules(),
        UnionRule(InferDependenciesRequest, InferCCDependenciesRequest),
    )
