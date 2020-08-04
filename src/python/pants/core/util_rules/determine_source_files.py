# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Iterable, Set, Tuple, Type, Union

from pants.base.specs import AddressSpec, OriginSpec
from pants.core.target_types import FilesSources
from pants.engine.addresses import Address
from pants.engine.fs import DigestSubset, MergeDigests, PathGlobs, Snapshot
from pants.engine.rules import Get, MultiGet, RootRule, collect_rules, rule
from pants.engine.target import HydratedSources, HydrateSourcesRequest
from pants.engine.target import Sources as SourcesField
from pants.util.meta import frozen_after_init


@dataclass(frozen=True)
class SourceFiles:
    """A merged snapshot of the `sources` fields of multiple targets.

    Possibly containing a subset of the `sources` when using `SpecifiedSourceFilesRequest` (instead
    of `AllSourceFilesRequest`).
    """

    snapshot: Snapshot

    # The subset of files in snapshot that are not intended to have an associated source root.
    # That is, the sources of files() targets.
    unrooted_files: Tuple[str, ...]

    @property
    def files(self) -> Tuple[str, ...]:
        return self.snapshot.files


@frozen_after_init
@dataclass(unsafe_hash=True)
class AllSourceFilesRequest:
    sources_fields: Tuple[SourcesField, ...]
    for_sources_types: Tuple[Type[SourcesField], ...]
    enable_codegen: bool

    def __init__(
        self,
        sources_fields: Iterable[SourcesField],
        *,
        for_sources_types: Iterable[Type[SourcesField]] = (SourcesField,),
        enable_codegen: bool = False,
    ) -> None:
        self.sources_fields = tuple(sources_fields)
        self.for_sources_types = tuple(for_sources_types)
        self.enable_codegen = enable_codegen


@frozen_after_init
@dataclass(unsafe_hash=True)
class SpecifiedSourceFilesRequest:
    sources_fields_with_origins: Tuple[Tuple[SourcesField, OriginSpec], ...]
    for_sources_types: Tuple[Type[SourcesField], ...]
    enable_codegen: bool

    def __init__(
        self,
        sources_fields_with_origins: Iterable[Tuple[SourcesField, OriginSpec]],
        *,
        for_sources_types: Iterable[Type[SourcesField]] = (SourcesField,),
        enable_codegen: bool = False,
    ) -> None:
        self.sources_fields_with_origins = tuple(sources_fields_with_origins)
        self.for_sources_types = tuple(for_sources_types)
        self.enable_codegen = enable_codegen


def calculate_specified_sources(
    sources_snapshot: Snapshot, address: Address, origin: OriginSpec
) -> Union[Snapshot, DigestSubset]:
    # AddressSpecs simply use the entire `sources` field. If it's a generated subtarget, we also
    # know we're as precise as we can get (1 file), so use the whole snapshot.
    if isinstance(origin, AddressSpec) or not address.is_base_target:
        return sources_snapshot
    # NB: we ensure that `precise_files_specified` is a subset of the original `sources` field.
    # It's possible when given a glob filesystem spec that the spec will have
    # resolved files not belonging to this target - those must be filtered out.
    precise_files_specified = set(sources_snapshot.files).intersection(origin.resolved_files)
    return DigestSubset(sources_snapshot.digest, PathGlobs(sorted(precise_files_specified)))


@rule
async def determine_all_source_files(request: AllSourceFilesRequest) -> SourceFiles:
    """Merge all `Sources` fields into one Snapshot."""
    unrooted_files: Set[str] = set()
    all_hydrated_sources = await MultiGet(
        Get(
            HydratedSources,
            HydrateSourcesRequest(
                sources_field,
                for_sources_types=request.for_sources_types,
                enable_codegen=request.enable_codegen,
            ),
        )
        for sources_field in request.sources_fields
    )

    for hydrated_sources, sources_field in zip(all_hydrated_sources, request.sources_fields):
        if isinstance(sources_field, FilesSources):
            unrooted_files.update(hydrated_sources.snapshot.files)

    digests_to_merge = tuple(
        hydrated_sources.snapshot.digest for hydrated_sources in all_hydrated_sources
    )
    result = await Get(Snapshot, MergeDigests(digests_to_merge))
    return SourceFiles(result, tuple(sorted(unrooted_files)))


@rule
async def determine_specified_source_files(request: SpecifiedSourceFilesRequest) -> SourceFiles:
    """Determine the specified `sources` for targets.

    Possibly finding a subset of the original `sources` fields if the user supplied file arguments.
    """
    all_unrooted_files: Set[str] = set()
    all_hydrated_sources = await MultiGet(
        Get(
            HydratedSources,
            HydrateSourcesRequest(
                sources_field_with_origin[0],
                for_sources_types=request.for_sources_types,
                enable_codegen=request.enable_codegen,
            ),
        )
        for sources_field_with_origin in request.sources_fields_with_origins
    )

    full_snapshots = {}
    digest_subset_requests = {}
    for hydrated_sources, sources_field_with_origin in zip(
        all_hydrated_sources, request.sources_fields_with_origins
    ):
        sources_field, origin = sources_field_with_origin
        if isinstance(sources_field, FilesSources):
            all_unrooted_files.update(hydrated_sources.snapshot.files)
        if not hydrated_sources.snapshot.files:
            continue
        specified_sources = calculate_specified_sources(
            hydrated_sources.snapshot, sources_field.address, origin
        )
        if isinstance(specified_sources, Snapshot):
            full_snapshots[sources_field] = specified_sources
        else:
            digest_subset_requests[sources_field] = specified_sources

    snapshot_subsets: Tuple[Snapshot, ...] = ()
    if digest_subset_requests:
        snapshot_subsets = await MultiGet(
            Get(Snapshot, DigestSubset, request) for request in digest_subset_requests.values()
        )

    all_snapshots: Iterable[Snapshot] = (*full_snapshots.values(), *snapshot_subsets)
    result = await Get(Snapshot, MergeDigests(snapshot.digest for snapshot in all_snapshots))
    unrooted_files = all_unrooted_files.intersection(result.files)
    return SourceFiles(result, tuple(sorted(unrooted_files)))


def rules():
    return [
        *collect_rules(),
        RootRule(AllSourceFilesRequest),
        RootRule(SpecifiedSourceFilesRequest),
    ]
