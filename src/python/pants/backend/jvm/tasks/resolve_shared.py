# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.base.build_environment import get_buildroot
from pants.engine.fs import PathGlobs, PathGlobsAndRoot
from pants.java.jar.jar_dependency_utils import ResolvedJar
from pants.task.task import TaskBase
from pants.util.dirutil import fast_relpath


class JvmResolverBase(TaskBase):
  """Common methods for both Ivy and Coursier resolves."""

  @classmethod
  def register_options(cls, register):
    """Register an option to make capturing snapshots optional.
    This class is intended to be extended by Jvm resolvers (coursier and ivy), and the option name should reflect that.
    """
    super(JvmResolverBase, cls).register_options(register)
    # TODO This flag should be defaulted to True when we are doing hermetic execution,
    # and should probably go away as we move forward into that direction.
    register('--capture-snapshots', type=bool, default=False,
      help='Enable capturing snapshots to add directory digests to dependency jars.'
           'Note that this is necessary when hermetic execution is enabled.')

  def add_directory_digests_for_jars(self, targets_and_jars):
    """For each target, get DirectoryDigests for its jars and return them zipped with the jars.

    :param targets_and_jars: List of tuples of the form (Target, [pants.java.jar.jar_dependency_utils.ResolveJar])
    :return: list[tuple[(Target, list[pants.java.jar.jar_dependency_utils.ResolveJar])]
    """

    targets_and_jars=list(targets_and_jars)

    if not targets_and_jars or not self.get_options().capture_snapshots:
      return targets_and_jars

    jar_paths = []
    for target, jars_to_snapshot in targets_and_jars:
      for jar in jars_to_snapshot:
        jar_paths.append(fast_relpath(jar.pants_path, get_buildroot()))

    snapshots = self.context._scheduler.capture_snapshots(
      tuple(
        PathGlobsAndRoot(PathGlobs([jar]), get_buildroot()) for jar in jar_paths
      ))

    # We want to map back the list[Snapshot] to targets_and_jars
    # We assume that (1) jars_to_snapshot has the same number of ResolveJars as snapshots does Snapshots,
    # and that (2) capture_snapshots preserves ordering.
    digests = [snapshot.directory_digest for snapshot in snapshots]
    digest_iterator = iter(digests)

    snapshotted_targets_and_jars = []
    for target, jars_to_snapshot in targets_and_jars:
      snapshotted_jars = [ResolvedJar(coordinate=jar.coordinate,
                                      cache_path=jar.cache_path,
                                      pants_path=jar.pants_path,
                                      directory_digest=digest_iterator.next()) for jar in jars_to_snapshot]
      snapshotted_targets_and_jars.append((target, snapshotted_jars))

    return snapshotted_targets_and_jars
