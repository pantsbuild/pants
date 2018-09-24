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

  def add_directory_digests_for_jars(self, jars):
    """Get DirectoryDigests for jars and return them zipped with the jars.

    :param jars: List of pants.java.jar.jar_dependency_utils.ResolveJar
    :return: List of ResolveJars.
    """
    snapshots = self.context._scheduler.capture_snapshots(
      tuple(PathGlobsAndRoot(
        PathGlobs([fast_relpath(jar.pants_path, get_buildroot())]), get_buildroot()) for jar in jars)
    )
    return [ResolvedJar(coordinate=jar.coordinate,
                        cache_path=jar.cache_path,
                        pants_path=jar.pants_path,
                        directory_digest=directory_digest) for jar, directory_digest in
            list(zip(jars, [snapshot.directory_digest for snapshot in snapshots]))]
