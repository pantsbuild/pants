# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.base.build_environment import get_buildroot
from pants.engine.fs import PathGlobsAndRoot, PathGlobs
from pants.util.dirutil import fast_relpath


class ResolveBase(object):
  """Common methods for both Ivy and Coursier resolves."""

  def jars_and_directory_digests_for_jars(self, jars):
    """Get DirectoryDigests for jars and return them zipped with the jars.

    :param jars: List of pants.java.jar.jar_dependency_utils.ResolveJar
    :return: List of tuples of ResolveJar and pants.engine.fs.DirectoryDigest
    """
    snapshots = self.context._scheduler.capture_snapshots(
      tuple(PathGlobsAndRoot(
        PathGlobs([fast_relpath(jar.pants_path, get_buildroot())]), get_buildroot()) for jar in jars)
    )
    return list(zip(jars, [snapshot.directory_digest for snapshot in snapshots]))
