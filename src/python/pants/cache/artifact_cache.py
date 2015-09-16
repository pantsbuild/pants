# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
import sys


# Note throughout the distinction between the artifact_root (which is where the artifacts are
# originally built and where the cache restores them to) and the cache root path/URL (which is
# where the artifacts are cached).

logger = logging.getLogger(__name__)


class ArtifactCacheError(Exception):
  pass


class NonfatalArtifactCacheError(Exception):
  pass


class UnreadableArtifact(object):
  """A False-y value to indicate a read-failure (vs a normal cache-miss)

  See docstring on `ArtifactCache.use_cached_files` for details.
  """

  def __init__(self, key, err=None):
    """
    :param CacheKey key: The key of the artifact that encountered an error
    :param err: Any additional information on the nature of the read error.
    """
    self.key = key
    self.err = err

  # For python 3
  def __bool__(self):
    return False

  # For python 2
  def __nonzero__(self):
    return self.__bool__()

  def __str__(self):
    return "key={} err={}".format(self.key, self.err)


class ArtifactCache(object):
  """A map from cache key to a set of build artifacts.

  The cache key must uniquely identify the inputs (sources, compiler flags etc.) needed to
  build the artifacts. Cache keys are typically obtained from a CacheKeyGenerator.

  Subclasses implement the methods below to provide this functionality.
  """

  def __init__(self, artifact_root):
    """Create an ArtifactCache.

    All artifacts must be under artifact_root.
    """
    self.artifact_root = artifact_root

  def prune(self):
    """Prune stale cache files

    Remove old unused cache files
    :return:
    """
    pass

  def insert(self, cache_key, paths, overwrite=False):
    """Cache the output of a build.

    By default, checks cache.has(key) first, only proceeding to create and insert an artifact
    if it is not already in the cache (though `overwrite` can be used to skip the check and
    unconditionally insert).

    :param CacheKey cache_key: A CacheKey object.
    :param list<str> paths: List of absolute paths to generated dirs/files.
                            These must be under the artifact_root.
    :param bool overwrite: Skip check for existing, insert even if already in cache.
    """
    missing_files = filter(lambda f: not os.path.exists(f), paths)
    if missing_files:
      raise ArtifactCacheError('Tried to cache nonexistent files {0}'.format(missing_files))

    if not overwrite:
      if self.has(cache_key):
        logger.debug('Skipping insert of existing artifact: {0}'.format(cache_key))
        return False

    try:
      self.try_insert(cache_key, paths)
      return True
    except NonfatalArtifactCacheError as e:
      logger.error('Error while writing to artifact cache: {0}'.format(e))
      return False

  def try_insert(self, cache_key, paths):
    """Attempt to cache the output of a build, without error-handling.

    :param CacheKey cache_key: A CacheKey object.
    :param list<str> paths: List of absolute paths to generated dirs/files. These must be under the artifact_root.
    """
    pass

  def has(self, cache_key):
    pass

  def use_cached_files(self, cache_key, hit_callback=None):
    """Use the files cached for the given key.

    Returned result indicates whether or not an artifact was successfully found
    and decompressed to the `artifact_root`:
      `True` if artifact was found and successfully decompressed
      `False` if not in the cache

    Implementations may choose to return an UnreadableArtifact instance instead
    of `False` to indicate an artifact was in the cache but could not be read,
    due to an error or corruption. UnreadableArtifact evaluates as False-y, so
    callers can treat the result as a boolean if they are only concerned with
    whether or not an artifact was read.

    Callers may also choose to attempt to repair or report corrupted artifacts
    differently, as these are unexpected, unlike normal cache misses.

    :param CacheKey cache_key: A CacheKey object.
    """
    pass

  def delete(self, cache_key):
    """Delete the artifacts for the specified key.

    Deleting non-existent artifacts is a no-op.
    :param CacheKey cache_key: A CacheKey object.
    """
    pass


def call_use_cached_files(tup):
  """Importable helper for multi-proc calling of ArtifactCache.use_cached_files on a cache instance.

  Multiprocessing map/apply/etc require functions which can be imported, not bound methods.
  To call a bound method, instead call a helper like this and pass tuple of the instance and args.
  The helper can then call the original method on the deserialized instance.

  :param tup: A tuple of an ArtifactCache and args (eg CacheKey) for ArtifactCache.use_cached_files.
  """

  try:
    cache, key, callback = tup
    res = cache.use_cached_files(key, callback)
    if res:
      sys.stderr.write('.')
    else:
      sys.stderr.write(' ')
    return res
  except NonfatalArtifactCacheError as e:
    logger.warn('Error calling use_cached_files in artifact cache: {0}'.format(e))
    return False


def call_insert(tup):
  """Importable helper for multi-proc calling of ArtifactCache.insert on an ArtifactCache instance.

  See docstring on call_use_cached_files explaining why this is useful.

  :param tup: A 4-tuple of an ArtifactCache and the 3 args passed to ArtifactCache.insert:
              eg (some_cache_instance, cache_key, [some_file, another_file], False)

  """
  try:
    cache, key, files, overwrite = tup
    return cache.insert(key, files, overwrite)
  except NonfatalArtifactCacheError as e:
    logger.warn('Error while inserting into artifact cache: {0}'.format(e))
    return False
