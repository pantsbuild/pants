# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
from contextlib import contextmanager

from pants.cache.artifact import TarballArtifact
from pants.cache.artifact_cache import ArtifactCache, UnreadableArtifact
from pants.util.contextutil import temporary_file
from pants.util.dirutil import safe_delete, safe_mkdir, safe_mkdir_for


logger = logging.getLogger(__name__)

class BaseLocalArtifactCache(ArtifactCache):
  def __init__(self, artifact_root, compression):
    """
    :param str artifact_root: The path under which cacheable products will be read/written.
    :param int compression: The gzip compression level for created artifacts.
                            Valid values are 0-9.
    """
    super(BaseLocalArtifactCache, self).__init__(artifact_root)
    self._compression = compression
    self._cache_root = None

  def _artifact(self, path):
    return TarballArtifact(self.artifact_root, path, self._compression)

  @contextmanager
  def _tmpfile(self, cache_key, use):
    """Allocate tempfile on same device as cache with a suffix chosen to prevent collisions"""
    with temporary_file(suffix=cache_key.id+use, root_dir=self._cache_root) as tmpfile:
      yield tmpfile

  @contextmanager
  def insert_paths(self, cache_key, paths):
    """Gather paths into artifact, store it, and yield the path to stored artifact tarball."""
    with self._tmpfile(cache_key, 'write') as tmp:
      self._artifact(tmp.name).collect(paths)
      yield self._store_tarball(cache_key, tmp.name)

  def store_and_use_artifact(self, cache_key, src):
    """
      Read the contents of an tarball from an iterator and return an artifact stored in the cache
    """
    with self._tmpfile(cache_key, 'read') as tmp:
      for chunk in src:
        tmp.write(chunk)
      tmp.close()
      self._artifact(self._store_tarball(cache_key, tmp.name)).extract()
      return True

  def _store_tarball(self, cache_key, src):
    """Given a src path to an artifact tarball, store it and return stored artifact's path."""
    pass

class LocalArtifactCache(BaseLocalArtifactCache):
  """An artifact cache that stores the artifacts in local files."""
  def __init__(self, artifact_root, cache_root, compression):
    """
    :param str artifact_root: The path under which cacheable products will be read/written.
    :param str cache_root: The locally cached files are stored under this directory.
    :param int compression: The gzip compression level for created artifacts (1-9 or false-y).
    """
    super(LocalArtifactCache, self).__init__(artifact_root, compression)
    self._cache_root = os.path.realpath(os.path.expanduser(cache_root))

    safe_mkdir(self._cache_root)

  def has(self, cache_key):
    return os.path.isfile(self._cache_file_for_key(cache_key))

  def _store_tarball(self, cache_key, src):
    dest = self._cache_file_for_key(cache_key)
    safe_mkdir_for(dest)
    os.rename(src, dest)
    return dest

  def use_cached_files(self, cache_key):
    try:
      tarfile = self._cache_file_for_key(cache_key)
      if os.path.exists(tarfile):
        self._artifact(tarfile).extract()
        return True
    except Exception as e:
      # TODO(davidt): Consider being more granular in what is caught.
      logger.warn('Error while reading from local artifact cache: {0}'.format(e))
      return UnreadableArtifact(cache_key, e)

    return False

  def try_insert(self, cache_key, paths):
    with self.insert_paths(cache_key, paths) as tmp:
      pass

  def delete(self, cache_key):
    safe_delete(self._cache_file_for_key(cache_key))

  def _cache_file_for_key(self, cache_key):
    # Note: it's important to use the id as well as the hash, because two different targets
    # may have the same hash if both have no sources, but we may still want to differentiate them.
    return os.path.join(self._cache_root, cache_key.id, cache_key.hash) + '.tgz'


class TempLocalArtifactCache(BaseLocalArtifactCache):
  """A local cache that does not actually store any files between calls.

    This implementation does not have a backing _cache_root, and never
    actually stores files between calls, but is useful for handling file IO for a remote cache.
  """
  def __init__(self, artifact_root, compression):
    """
    :param str artifact_root: The path under which cacheable products will be read/written.
    """
    super(TempLocalArtifactCache, self).__init__(artifact_root, compression=compression)

  def _store_tarball(self, cache_key, src):
    return src

  def has(self, cache_key):
    return False

  def use_cached_files(self, cache_key):
    return False

  def delete(self, cache_key):
    pass
