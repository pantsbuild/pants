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
from pants.util.dirutil import (safe_delete, safe_mkdir, safe_mkdir_for,
                                safe_rm_oldest_items_in_dir, safe_rmtree)


logger = logging.getLogger(__name__)


class BaseLocalArtifactCache(ArtifactCache):

  def __init__(self, artifact_root, compression, permissions=None, dereference=True):
    """
    :param str artifact_root: The path under which cacheable products will be read/written.
    :param int compression: The gzip compression level for created artifacts.
                            Valid values are 0-9.
    :param str permissions: File permissions to use when creating artifact files.
    :param bool dereference: Dereference symlinks when creating the cache tarball.
    """
    super(BaseLocalArtifactCache, self).__init__(artifact_root)
    self._compression = compression
    self._cache_root = None
    self._permissions = permissions
    self._dereference = dereference

  def _artifact(self, path):
    return TarballArtifact(self.artifact_root, path, self._compression, dereference=self._dereference)

  @contextmanager
  def _tmpfile(self, cache_key, use):
    """Allocate tempfile on same device as cache with a suffix chosen to prevent collisions"""
    with temporary_file(suffix=cache_key.id + use, root_dir=self._cache_root,
                        permissions=self._permissions) as tmpfile:
      yield tmpfile

  @contextmanager
  def insert_paths(self, cache_key, paths):
    """Gather paths into artifact, store it, and yield the path to stored artifact tarball."""
    with self._tmpfile(cache_key, 'write') as tmp:
      self._artifact(tmp.name).collect(paths)
      yield self._store_tarball(cache_key, tmp.name)

  def store_and_use_artifact(self, cache_key, src, results_dir=None):
    """Store and then extract the artifact from the given `src` iterator for the given cache_key.

    :param cache_key: Cache key for the artifact.
    :param src: Iterator over binary data to store for the artifact.
    :param str results_dir: The path to the expected destination of the artifact extraction: will
      be cleared both before extraction, and after a failure to extract.
    """
    with self._tmpfile(cache_key, 'read') as tmp:
      for chunk in src:
        tmp.write(chunk)
      tmp.close()
      tarball = self._store_tarball(cache_key, tmp.name)
      artifact = self._artifact(tarball)

      if results_dir is not None:
        safe_mkdir(results_dir, clean=True)

      try:
        artifact.extract()
      except Exception:
        # Do our best to clean up after a failed artifact extraction. If a results_dir has been
        # specified, it is "expected" to represent the output destination of the extracted
        # artifact, and so removing it should clear any partially extracted state.
        if results_dir is not None:
          safe_mkdir(results_dir, clean=True)
        safe_delete(tarball)
        raise

      return True

  def _store_tarball(self, cache_key, src):
    """Given a src path to an artifact tarball, store it and return stored artifact's path."""
    pass


class LocalArtifactCache(BaseLocalArtifactCache):
  """An artifact cache that stores the artifacts in local files."""

  def __init__(self, artifact_root, cache_root, compression, max_entries_per_target=None,
               permissions=None, dereference=True):
    """
    :param str artifact_root: The path under which cacheable products will be read/written.
    :param str cache_root: The locally cached files are stored under this directory.
    :param int compression: The gzip compression level for created artifacts (1-9 or false-y).
    :param int max_entries_per_target: The maximum number of old cache files to leave behind on a cache miss.
    :param str permissions: File permissions to use when creating artifact files.
    :param bool dereference: Dereference symlinks when creating the cache tarball.
    """
    super(LocalArtifactCache, self).__init__(
      artifact_root,
      compression,
      permissions=int(permissions.strip(), base=8) if permissions else None,
      dereference=dereference
    )
    self._cache_root = os.path.realpath(os.path.expanduser(cache_root))
    self._max_entries_per_target = max_entries_per_target
    safe_mkdir(self._cache_root)

  def prune(self, root):
    """Prune stale cache files

    If the option --cache-target-max-entry is greater than zero, then prune will remove all but n
    old cache files for each target/task.

    :param str root: The path under which cacheable artifacts will be cleaned
    """

    max_entries_per_target = self._max_entries_per_target
    if os.path.isdir(root) and max_entries_per_target:
      safe_rm_oldest_items_in_dir(root, max_entries_per_target)

  def has(self, cache_key):
    return self._artifact_for(cache_key).exists()

  def _artifact_for(self, cache_key):
    return self._artifact(self._cache_file_for_key(cache_key))

  def use_cached_files(self, cache_key, results_dir=None):
    tarfile = self._cache_file_for_key(cache_key)
    try:
      artifact = self._artifact_for(cache_key)
      if artifact.exists():
        if results_dir is not None:
          safe_rmtree(results_dir)
        artifact.extract()
        return True
    except Exception as e:
      # TODO(davidt): Consider being more granular in what is caught.
      logger.warn('Error while reading {0} from local artifact cache: {1}'.format(tarfile, e))
      safe_delete(tarfile)
      return UnreadableArtifact(cache_key, e)

    return False

  def try_insert(self, cache_key, paths):
    with self.insert_paths(cache_key, paths):
      pass

  def delete(self, cache_key):
    safe_delete(self._cache_file_for_key(cache_key))

  def _store_tarball(self, cache_key, src):
    dest = self._cache_file_for_key(cache_key)
    safe_mkdir_for(dest)
    os.rename(src, dest)
    if self._permissions:
      os.chmod(dest, self._permissions)
    self.prune(os.path.dirname(dest))  # Remove old cache files.
    return dest

  def _cache_file_for_key(self, cache_key):
    # Note: it's important to use the id as well as the hash, because two different targets
    # may have the same hash if both have no sources, but we may still want to differentiate them.
    return os.path.join(self._cache_root, cache_key.id, cache_key.hash) + '.tgz'


class TempLocalArtifactCache(BaseLocalArtifactCache):
  """A local cache that does not actually store any files between calls.

  This implementation does not have a backing _cache_root, and never
  actually stores files between calls, but is useful for handling file IO for a remote cache.
  """

  def __init__(self, artifact_root, compression, permissions=None):
    """
    :param str artifact_root: The path under which cacheable products will be read/written.
    """
    super(TempLocalArtifactCache, self).__init__(artifact_root, compression=compression,
                                                 permissions=permissions)

  def _store_tarball(self, cache_key, src):
    return src

  def has(self, cache_key):
    return False

  def use_cached_files(self, cache_key, results_dir=None):
    return False

  def delete(self, cache_key):
    pass
