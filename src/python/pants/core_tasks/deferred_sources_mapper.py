# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os

from pants.base.build_environment import get_buildroot
from pants.build_graph.address import Address
from pants.build_graph.address_lookup_error import AddressLookupError
from pants.build_graph.remote_sources import RemoteSources
from pants.engine.fs import PathGlobs, PathGlobsAndRoot
from pants.source.wrapped_globs import EagerFilesetWithSpec
from pants.task.task import Task
from pants.task.unpack_remote_sources_base import UnpackedArchives

logger = logging.getLogger(__name__)


class DeferredSourcesMapper(Task):
    """Map `remote_sources()` to files that produce the product `UnpackedArchives`.

    If you want a task to be able to map sources like this, make it require the 'deferred_sources'
    product.
    """

    class SourcesTargetLookupError(AddressLookupError):
        """Raised when the referenced target cannot be found in the build graph."""

        pass

    class NoUnpackedSourcesError(AddressLookupError):
        """Raised when there are no files found unpacked from the archive."""

        pass

    @classmethod
    def product_types(cls):
        """Declare product produced by this task.

        deferred_sources does not have any data associated with it. Downstream tasks can
        depend on it just make sure that this task completes first.
        :return:
        """
        return ["deferred_sources"]

    @classmethod
    def prepare(cls, options, round_manager):
        round_manager.require_data(UnpackedArchives)

    def process_remote_sources(self):
        """Create synthetic targets with populated sources from remote_sources targets."""
        unpacked_sources = self.context.products.get_data(UnpackedArchives)
        remote_sources_targets = self.context.targets(
            predicate=lambda t: isinstance(t, RemoteSources)
        )
        if not remote_sources_targets:
            return

        snapshot_specs = []
        filespecs = []
        unpack_dirs = []
        for target in remote_sources_targets:
            unpacked_archive = unpacked_sources[target.sources_target]
            sources = unpacked_archive.found_files
            rel_unpack_dir = unpacked_archive.rel_unpack_dir
            self.context.log.debug(
                "target: {}, rel_unpack_dir: {}, sources: {}".format(
                    target, rel_unpack_dir, sources
                )
            )
            sources_in_dir = tuple(os.path.join(rel_unpack_dir, source) for source in sources)
            snapshot_specs.append(PathGlobsAndRoot(PathGlobs(sources_in_dir), get_buildroot(),))
            filespecs.append({"globs": sources_in_dir})
            unpack_dirs.append(rel_unpack_dir)

        snapshots = self.context._scheduler.capture_snapshots(tuple(snapshot_specs))
        for target, snapshot, filespec, rel_unpack_dir in zip(
            remote_sources_targets, snapshots, filespecs, unpack_dirs
        ):
            synthetic_target = self.context.add_new_target(
                address=Address(os.path.relpath(self.workdir, get_buildroot()), target.id),
                target_type=target.destination_target_type,
                dependencies=target.dependencies,
                sources=EagerFilesetWithSpec(rel_unpack_dir, filespec, snapshot),
                derived_from=target,
                **target.destination_target_args
            )
            self.context.log.debug("synthetic_target: {}".format(synthetic_target))
            for dependent in self.context.build_graph.dependents_of(target.address):
                self.context.build_graph.inject_dependency(dependent, synthetic_target.address)

    def execute(self):
        self.process_remote_sources()
