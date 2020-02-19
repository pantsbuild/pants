# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from hashlib import sha1
from typing import TYPE_CHECKING, Any, List, Optional, Union, cast

from pants.base.payload_field import PayloadField
from pants.engine.fs import PathGlobs, Snapshot
from pants.source.filespec import matches_filespec
from pants.source.source_root import SourceRootConfig
from pants.source.wrapped_globs import EagerFilesetWithSpec, FilesetWithSpec, Filespec
from pants.util.memo import memoized_property

if TYPE_CHECKING:
    from pants.engine.scheduler import SchedulerSession  # noqa: F401


class SourcesField(PayloadField):
    """A PayloadField encapsulating specified sources."""

    @staticmethod
    def _validate_sources(sources: Union[Any, FilesetWithSpec]) -> FilesetWithSpec:
        if not isinstance(sources, FilesetWithSpec):
            raise ValueError(
                "Expected a FilesetWithSpec. `sources` should be "
                "instantiated via `create_sources_field`."
            )
        return sources

    def __init__(self, sources: FilesetWithSpec, ref_address=None) -> None:
        """
        :param sources: FilesetWithSpec representing the underlying sources.
        :param ref_address: optional address spec of target that provides these sources
        """
        self._sources = self._validate_sources(sources)
        self._ref_address = ref_address

    @property
    def source_root(self):
        """:returns: the source root for these sources, or None if they're not under a source root."""
        # TODO: It's a shame that we have to access the singleton directly here, instead of getting
        # the SourceRoots instance from context, as tasks do.  In the new engine we could inject
        # this into the target, rather than have it reach out for global singletons.
        return SourceRootConfig.global_instance().get_source_roots().find_by_path(self.rel_path)

    def matches(self, path: str) -> bool:
        return self.sources.matches(path) or matches_filespec(path, self.filespec)

    @property
    def filespec(self) -> Filespec:
        return self.sources.filespec

    @property
    def rel_path(self) -> str:
        return self.sources.rel_root

    @property
    def sources(self) -> FilesetWithSpec:
        return self._sources

    @memoized_property
    def source_paths(self) -> List[str]:
        return list(self.sources)

    @property
    def address(self):
        """Returns the address this sources field refers to (used by some derived classes)"""
        return self._ref_address

    def snapshot(self, scheduler: Optional["SchedulerSession"] = None) -> Snapshot:
        """Returns a Snapshot containing the sources, relative to the build root.

        This API is experimental, and subject to change.
        """
        if isinstance(self._sources, EagerFilesetWithSpec):
            return self._sources.snapshot
        if scheduler is None:
            raise AssertionError(
                "Sources is not an EagerFilesetWithSpec and this function was called with "
                "`scheduler=None`. Change the call site to pass the parameter `scheduler`."
            )
        input_pathglobs = PathGlobs(tuple(self.relative_to_buildroot()))
        return cast(Snapshot, scheduler.product_request(Snapshot, [input_pathglobs])[0])

    def relative_to_buildroot(self) -> List[str]:
        """All sources joined with their relative paths."""
        return list(self.sources.paths_from_buildroot_iter())

    def _compute_fingerprint(self) -> str:
        hasher = sha1()
        hasher.update(self.rel_path.encode())
        hasher.update(self.sources.files_hash)
        return hasher.hexdigest()
