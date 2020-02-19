# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from pathlib import PurePath
from typing import cast

from pants.build_graph.files import Files
from pants.engine.fs import EMPTY_SNAPSHOT, Digest, DirectoryWithPrefixToStrip, Snapshot
from pants.engine.legacy.graph import HydratedTarget
from pants.engine.rules import rule, subsystem_rule
from pants.engine.selectors import Get
from pants.source.source_root import NoSourceRootError, SourceRootConfig


@dataclass(frozen=True)
class SourceRootStrippedSources:
    """Wrapper for a snapshot of targets whose source roots have been stripped."""

    snapshot: Snapshot


@dataclass(frozen=True)
class StripSourceRootsRequest:
    """A request to strip source roots for every file in the snapshot.

    The field `representative_path` is used to determine the source root for the files to be stripped.
    This assumes that every file shares the same source root, which should be true in practice as the
    `sources` field for a target always has files in the same source root. We don't proactively
    validate this assumption because of the performance implications of running
    `SourceRoots.find_by_path` on every single file in the snapshot, as opposed to only one file. See
    https://github.com/pantsbuild/pants/pull/9112#discussion_r377999025 for more context on this
    design.
    """

    snapshot: Snapshot
    representative_path: str

    def determine_source_root(self, *, source_root_config: SourceRootConfig) -> str:
        source_roots_object = source_root_config.get_source_roots()
        source_root = source_roots_object.safe_find_by_path(self.representative_path)
        if source_root is not None:
            return cast(str, source_root.path)
        if source_root_config.options.unmatched == "fail":
            raise NoSourceRootError(
                f"Could not find a source root for `{self.representative_path}`."
            )
        # Otherwise, create a source root by using the parent directory.
        return PurePath(self.representative_path).parent.as_posix()


@rule
async def strip_source_roots_from_snapshot(
    request: StripSourceRootsRequest, source_root_config: SourceRootConfig,
) -> SourceRootStrippedSources:
    """Removes source roots from a snapshot, e.g. `src/python/pants/util/strutil.py` ->
    `pants/util/strutil.py`."""
    source_root = request.determine_source_root(source_root_config=source_root_config)
    resulting_digest = await Get[Digest](
        DirectoryWithPrefixToStrip(
            directory_digest=request.snapshot.directory_digest, prefix=source_root,
        )
    )
    resulting_snapshot = await Get[Snapshot](Digest, resulting_digest)
    return SourceRootStrippedSources(snapshot=resulting_snapshot)


@rule
async def strip_source_roots_from_target(
    hydrated_target: HydratedTarget,
) -> SourceRootStrippedSources:
    """Remove source roots from a target, e.g. `src/python/pants/util/strutil.py` ->
    `pants/util/strutil.py`."""
    target_adaptor = hydrated_target.adaptor

    # TODO: make TargetAdaptor return a 'sources' field with an empty snapshot instead of raising to
    # simplify the hasattr() checks here!
    if not hasattr(target_adaptor, "sources"):
        return SourceRootStrippedSources(snapshot=EMPTY_SNAPSHOT)

    # Loose `Files`, as opposed to `Resources` or `Target`s, have no (implied) package
    # structure and so we do not remove their source root like we normally do, so that filesystem
    # APIs may still access the files. See pex_build_util.py's `_create_source_dumper`.
    if target_adaptor.type_alias == Files.alias():
        return SourceRootStrippedSources(snapshot=target_adaptor.sources.snapshot)

    build_file = PurePath(hydrated_target.address.spec_path, "BUILD").as_posix()
    return await Get[SourceRootStrippedSources](
        StripSourceRootsRequest(target_adaptor.sources.snapshot, representative_path=build_file)
    )


def rules():
    return [
        strip_source_roots_from_snapshot,
        strip_source_roots_from_target,
        subsystem_rule(SourceRootConfig),
    ]
