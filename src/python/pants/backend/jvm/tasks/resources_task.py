# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from abc import abstractmethod

from pants.backend.jvm.tasks.classpath_entry import ClasspathEntry
from pants.base.build_environment import get_buildroot
from pants.engine.fs import Digest, PathGlobs, PathGlobsAndRoot
from pants.task.task import Task
from pants.util.dirutil import fast_relpath


class ResourcesTask(Task):
    """A base class for tasks that process or create resource files.

    This base assumes that resources targets or targets that generate resources are independent from
    each other and can be processed in isolation in any order.

    :API: public
    """

    @classmethod
    def product_types(cls):
        return ["runtime_classpath"]

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--confs",
            advanced=True,
            type=list,
            default=["default"],
            help="Prepare resources for these Ivy confs.",
        )

    @classmethod
    def prepare(cls, options, round_manager):
        round_manager.require_data("compile_classpath")

    @property
    def cache_target_dirs(self):
        return True

    def execute(self):
        # Tracked and returned for use in tests.
        # TODO: Rewrite those tests. execute() is not supposed to return anything.
        processed_targets = []

        compile_classpath = self.context.products.get_data("compile_classpath")
        runtime_classpath = self.context.products.get_data(
            "runtime_classpath", compile_classpath.copy
        )

        all_relevant_resources_targets = self.find_all_relevant_resources_targets()
        if not all_relevant_resources_targets:
            return processed_targets

        with self.invalidated(
            targets=all_relevant_resources_targets,
            fingerprint_strategy=self.create_invalidation_strategy(),
            invalidate_dependents=False,
            topological_order=False,
        ) as invalidation:
            for vt in invalidation.invalid_vts:
                # Generate resources to the chroot.
                self.prepare_resources(vt.target, vt.results_dir)
                processed_targets.append(vt.target)
            for vt, digest in self._capture_resources(invalidation.all_vts):
                # Register the target's chroot in the products.
                for conf in self.get_options().confs:
                    runtime_classpath.add_for_target(
                        vt.target, [(conf, ClasspathEntry(vt.results_dir, digest))]
                    )

        return processed_targets

    def _capture_resources(self, vts):
        """Given a list of VersionedTargets, capture DirectoryDigests for all of them.

        :returns: A list of tuples of VersionedTargets and digests for their content.
        """
        # Capture Snapshots for each directory, using an optional adjacent digest. Create the digest
        # afterward if it does not exist.
        buildroot = get_buildroot()
        snapshots = self.context._scheduler.capture_snapshots(
            tuple(
                PathGlobsAndRoot(
                    PathGlobs([os.path.join(fast_relpath(vt.results_dir, buildroot), "**")]),
                    buildroot,
                    Digest.load(vt.current_results_dir),
                )
                for vt in vts
            )
        )
        result = []
        for vt, snapshot in zip(vts, snapshots):
            snapshot.directory_digest.dump(vt.current_results_dir)
            result.append((vt, snapshot.directory_digest))
        return result

    @abstractmethod
    def find_all_relevant_resources_targets(self):
        """Returns an iterable over all the relevant resources targets in the context."""

    def create_invalidation_strategy(self):
        """Creates a custom fingerprint strategy for determining invalid resources targets.

        :returns: A custom fingerprint strategy to use for determining invalid targets, or `None` to
                  use the standard target payload.
        :rtype: :class:`pants.base.fingerprint_strategy.FingerprintStrategy`
        """
        return None

    @abstractmethod
    def prepare_resources(self, target, chroot):
        """Prepares the resources associated with `target` in the given `chroot`.

        :param target: The target to prepare resource files for.
        :type target: :class:`pants.build_graph.target.Target`
        :param string chroot: An existing, clean chroot dir to generate `target`'s resources to.
        """
