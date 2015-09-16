# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import errno
import os
import shutil
import tarfile

from pants.util.contextutil import open_tar
from pants.util.dirutil import safe_mkdir, safe_mkdir_for, safe_walk


class ArtifactError(Exception):
  pass


class Artifact(object):
  """Represents a set of files in an artifact."""

  def __init__(self, artifact_root):
    # All files must be under this root.
    self._artifact_root = artifact_root

    # The files known to be in this artifact, relative to artifact_root.
    self._relpaths = set()

  def exists(self):
    """:returns True if the artifact is available for extraction."""
    raise NotImplementedError()

  def get_paths(self):
    for relpath in self._relpaths:
      yield os.path.join(self._artifact_root, relpath)

  def override_paths(self, paths):  # Use with care.
    self._relpaths = set([os.path.relpath(path, self._artifact_root) for path in paths])

  def collect(self, paths):
    """Collect the paths (which must be under artifact root) into this artifact."""
    raise NotImplementedError()

  def extract(self):
    """Extract the files in this artifact to their locations under artifact root."""
    raise NotImplementedError()


class DirectoryArtifact(Artifact):
  """An artifact stored as loose files under a directory."""

  def __init__(self, artifact_root, directory):
    Artifact.__init__(self, artifact_root)
    self._directory = directory

  def exists(self):
    return os.path.exists(self._directory)

  def collect(self, paths):
    for path in paths or ():
      relpath = os.path.relpath(path, self._artifact_root)
      dst = os.path.join(self._directory, relpath)
      safe_mkdir(os.path.dirname(dst))
      if os.path.isdir(path):
        shutil.copytree(path, dst)
      else:
        shutil.copy(path, dst)
      self._relpaths.add(relpath)

  def extract(self):
    for dir_name, _, filenames in safe_walk(self._directory):
      for filename in filenames:
        filename = os.path.join(dir_name, filename)
        relpath = os.path.relpath(filename, self._directory)
        dst = os.path.join(self._artifact_root, relpath)
        safe_mkdir_for(dst)
        shutil.copy(filename, dst)
        self._relpaths.add(relpath)


class TarballArtifact(Artifact):
  """An artifact stored in a tarball."""

  def __init__(self, artifact_root, tarfile, compression=9):
    Artifact.__init__(self, artifact_root)
    self._tarfile = tarfile
    self._compression = compression

  def exists(self):
    return os.path.isfile(self._tarfile)

  def collect(self, paths):
    # In our tests, gzip is slightly less compressive than bzip2 on .class files,
    # but decompression times are much faster.
    mode = 'w:gz'

    tar_kwargs = {'dereference': True, 'errorlevel': 2}
    tar_kwargs['compresslevel'] = self._compression

    with open_tar(self._tarfile, mode, **tar_kwargs) as tarout:
      for path in paths or ():
        # Adds dirs recursively.
        relpath = os.path.relpath(path, self._artifact_root)
        tarout.add(path, relpath)
        self._relpaths.add(relpath)

  def extract(self):
    try:
      with open_tar(self._tarfile, 'r', errorlevel=2) as tarin:
        # Note: We create all needed paths proactively, even though extractall() can do this for us.
        # This is because we may be called concurrently on multiple artifacts that share directories,
        # and there will be a race condition inside extractall(): task T1 A) sees that a directory
        # doesn't exist and B) tries to create it. But in the gap between A) and B) task T2 creates
        # the same directory, so T1 throws "File exists" in B).
        # This actually happened, and was very hard to debug.
        # Creating the paths here up front allows us to squelch that "File exists" error.
        paths = []
        dirs = set()
        for tarinfo in tarin.getmembers():
          paths.append(tarinfo.name)
          if tarinfo.isdir():
            dirs.add(tarinfo.name)
          else:
            dirs.add(os.path.dirname(tarinfo.name))
        for d in dirs:
          try:
            os.makedirs(os.path.join(self._artifact_root, d))
          except OSError as e:
            if e.errno != errno.EEXIST:
              raise
        tarin.extractall(self._artifact_root)
        self._relpaths.update(paths)
    except tarfile.ReadError as e:
      raise ArtifactError(str(e))
