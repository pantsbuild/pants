# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
import logging
from dataclasses import dataclass
from pathlib import PurePath
from typing import Iterable, Set, Tuple, Type

from pants.core.target_types import (
    FilesGeneratingSourcesField,
    FileSourceField,
    ResourcesGeneratingSourcesField,
    ResourceSourceField,
)
from pants.engine.fs import Digest, DigestSubset, MergeDigests, PathGlobs, Snapshot
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import HydratedSources, HydrateSourcesRequest, SourcesField
from pants.util.docutil import doc_url
from pants.util.meta import frozen_after_init
from pants.util.strutil import bullet_list, softwrap

_ASSET_SF_TYPES = (
    FileSourceField,
    FilesGeneratingSourcesField,
    ResourceSourceField,
    ResourcesGeneratingSourcesField,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SourceFiles:
    """A merged snapshot of the `sources` fields of multiple targets."""

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
    ignore_unparented_assets: bool

    def __init__(
        self,
        sources_fields: Iterable[SourcesField],
        *,
        for_sources_types: Iterable[Type[SourcesField]] = (SourcesField,),
        enable_codegen: bool = False,
        ignore_unparented_assets: bool = False,
    ) -> None:
        self.sources_fields = tuple(sources_fields)
        self.for_sources_types = tuple(for_sources_types)
        self.enable_codegen = enable_codegen
        self.ignore_unparented_assets = ignore_unparented_assets


def _get_unparented_assets(
    all_hydrated_sources: Tuple[HydratedSources, ...],
    sources_fields: Tuple[SourcesField, ...],
) -> Set[PurePath]:
    asset_paths: Set[PurePath] = set()
    primary_source_dirs: Set[PurePath] = set()
    for hydrated_sources, sources_field in zip(all_hydrated_sources, sources_fields):
        paths = (PurePath(f) for f in hydrated_sources.snapshot.files)
        if isinstance(sources_field, _ASSET_SF_TYPES):
            asset_paths.update(paths)
        else:
            primary_source_dirs.update(
                itertools.chain.from_iterable(path.parents for path in paths)
            )

    unparented_assets = set()
    for path in asset_paths:
        if path.parent not in primary_source_dirs:
            unparented_assets.add(path)

    if unparented_assets:
        logger.warning(
            softwrap(
                f"""
                Found one or more "unparented" assets when attempting to collect the relevant sources
                for the current goal. "Unparented" assets are assets in a directory _above_ all
                other non-asset sources, and will be ignored.

                If you want the assets copied lower in the source tree for this goal, use and depend
                on a `relocated_files` target with the appropriate fields set.

                If you want the assets deployed in the same directory tree as they are in your repo,
                use an `archive` target which depends on the relevant assets, and your packageable
                target.

                See {doc_url('assets')}.

                Unparented assets:
                {bullet_list(str(asset) for asset in unparented_assets)}
                """
            )
        )
    return unparented_assets


@rule(desc="Get all relevant source files")
async def determine_source_files(request: SourceFilesRequest) -> SourceFiles:
    """Merge all `SourceBaseField`s into one Snapshot."""
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

    paths_to_ignore: Set[PurePath] = set()
    if request.ignore_unparented_assets:
        paths_to_ignore = _get_unparented_assets(all_hydrated_sources, request.sources_fields)

    for hydrated_sources, sources_field in zip(all_hydrated_sources, request.sources_fields):
        if not sources_field.uses_source_roots:
            unrooted_files.update(hydrated_sources.snapshot.files)

    digests_to_merge = tuple(
        hydrated_sources.snapshot.digest for hydrated_sources in all_hydrated_sources
    )
    result_digest = await Get(Digest, MergeDigests(digests_to_merge))
    if paths_to_ignore:
        all_files = set(
            itertools.chain.from_iterable(
                hydrated_sources.snapshot.files for hydrated_sources in all_hydrated_sources
            )
        )
        result_digest = await Get(
            Digest,
            DigestSubset(
                result_digest,
                PathGlobs(file for file in all_files if PurePath(file) not in paths_to_ignore),
            ),
        )
    result_snapshot = await Get(Snapshot, Digest, result_digest)
    return SourceFiles(result_snapshot, tuple(sorted(unrooted_files)))


def rules():
    return collect_rules()
