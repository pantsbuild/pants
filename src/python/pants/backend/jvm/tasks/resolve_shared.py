# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.base.build_environment import get_buildroot
from pants.engine.fs import PathGlobs, PathGlobsAndRoot
from pants.java.jar.jar_dependency_utils import ResolvedJar
from pants.util.dirutil import fast_relpath


class ResolveBase(object):
  """Common methods for both Ivy and Coursier resolves."""

  def add_directory_digests_for_jars(self, targets_and_jars):
    """For each target, get DirectoryDigests for its jars and return them zipped with the jars.

    :param targets_and_jars: List of tuples of the form (Target, [pants.java.jar.jar_dependency_utils.ResolveJar])
    :return: list[tuple[(Target, list[pants.java.jar.jar_dependency_utils.ResolveJar])]
    """

    # Unzip into a tuple[list[ResolveJar]] (jars_to_snapshot)
    targets_and_jars=list(targets_and_jars)
    print("TARGETS AND JARS: ", targets_and_jars)

    if not targets_and_jars:
      print("asdfasdfasdfasdfasdfasdflkasdjfkjashdfklasdhf")
      return targets_and_jars

    # [(target, [jars]), (target, [jars])] -> ([target, target], [[jars], [jars]])
    print("TARGETS AND JARS - 2: ", targets_and_jars)
    jar_paths = [] # list[list[jar]]
    for target, jars_to_snapshot in targets_and_jars:
      for jar in jars_to_snapshot:
        jar_paths.append(fast_relpath(jar.pants_path, get_buildroot()))

    print("JAR PATHS: ", jar_paths)
    #
    # def create_pathglobs(jars):
    #   return PathGlobs([fast_relpath(jar.pants_path, get_buildroot()) for jar in jars])
    #
    # globs = tuple([PathGlobsAndRoot(create_pathglobs(jars), get_buildroot()) for jars in jars_to_snapshot])
    # print("GLOBS ", globs)
    snapshots = self.context._scheduler.capture_snapshots(
      tuple(
        PathGlobsAndRoot(PathGlobs([jar]), get_buildroot()) for jar in jar_paths
      ))
    print("SNAPSHOTS ", snapshots)

    # We want to map back the list[Snapshot] to targets_and_jars
    # We assume that (1) jars_to_snapshot has the same number of ResolveJars as snapshots does Snapshots,
    # and that (2) capture_snapshots preserves ordering.
    digests = [snapshot.directory_digest for snapshot in snapshots]
    print("DIGESTS ", digests)
    digest_iterator = iter(digests)

    snapshotted_targets_and_jars = []
    print("Targets nad jars: ", targets_and_jars)
    for target, jars_to_snapshot in targets_and_jars:
      snapshotted_jars = [ResolvedJar(coordinate=jar.coordinate,
                                      cache_path=jar.cache_path,
                                      pants_path=jar.pants_path,
                                      directory_digest=digest_iterator.next()) for jar in jars_to_snapshot]
      print("SNAPSHOTTED JARS: ", snapshotted_jars)
      snapshotted_targets_and_jars.append((target, snapshotted_jars))

    print("AFTER SNAPSHOT: ", snapshotted_targets_and_jars)
    return snapshotted_targets_and_jars
