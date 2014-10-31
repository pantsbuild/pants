# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import logging
import os

# Note throughout the distinction between the artifact_root (which is where the artifacts are
# originally built and where the cache restores them to) and the cache root path/URL (which is
# where the artifacts are cached).

logger = logging.getLogger(__name__)

class ArtifactCacheError(Exception):
  pass

class NonfatalArtifactCacheError(Exception):
  pass

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

  def insert(self, cache_key, paths):
    """Cache the output of a build.

    If there is an existing set of artifacts for this key they are deleted.

    TODO: Check that they're equal? They might not have to be if there are multiple equivalent
          outputs.

    :param CacheKey cache_key: A CacheKey object.
    :param list<str> paths: List of absolute paths to generated dirs/files. These must be under the artifact_root.
    """
    missing_files = filter(lambda f: not os.path.exists(f), paths)
    try:
      if missing_files:
        raise ArtifactCacheError('Tried to cache nonexistent files {0}'.format(missing_files))
      self.try_insert(cache_key, paths)
      return True
    except NonfatalArtifactCacheError as e:
      logger.error('Error while writing to artifact cache: {0}. '.format(e))
      return False

  def try_insert(self, cache_key, paths):
    """Attempt to cache the output of a build, without error-handling.

    :param CacheKey cache_key: A CacheKey object.
    :param list<str> paths: List of absolute paths to generated dirs/files. These must be under the artifact_root.
    """
    pass

  def has(self, cache_key):
    pass

  def use_cached_files(self, cache_key):
    """Use the files cached for the given key.

    Returns an appropriate Artifact instance if files were found and used, None otherwise.
    Callers will typically only care about the truthiness of the return value. They usually
    don't need to tinker with the returned instance.

    :param CacheKey cache_key: A CacheKey object.
    """
    pass

  def delete(self, cache_key):
    """Delete the artifacts for the specified key.

    Deleting non-existent artifacts is a no-op.
    :param CacheKey cache_key: A CacheKey object.
    """
    pass
