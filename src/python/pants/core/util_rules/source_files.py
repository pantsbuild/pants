# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Iterable, Set, Tuple, Type

from pants.core.target_types import FilesSources
from pants.engine.fs import MergeDigests, Snapshot
from pants.engine.rules import Get, MultiGet, collect_rules, rule
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
class SourceFilesRequest:
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


@rule(desc="Get all relevant source files")
async def determine_source_files(request: SourceFilesRequest) -> SourceFiles:
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


def rules():
    return collect_rules()
