# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.cache.artifact_cache import ArtifactCache


class CombinedArtifactCache(ArtifactCache):
  """An artifact cache that delegates to a list of other caches."""
  def __init__(self, artifact_caches, backfill=True):
    """We delegate to artifact_caches, a list of ArtifactCache instances, in order.

    If backfill is true then we populate earlier caches that were missing an artifact,
    if that artifact was found in a later cache. This is useful for priming a local cache
    from a remote one.
    """
    if not artifact_caches:
      raise ValueError('Must provide at least one underlying artifact cache')
    log = artifact_caches[0].log
    artifact_root = artifact_caches[0].artifact_root
    if any(x.artifact_root != artifact_root for x in artifact_caches):
      raise ValueError('Combined artifact caches must all have the same artifact root.')
    ArtifactCache.__init__(self, log, artifact_root)
    self._artifact_caches = artifact_caches
    self._backfill = backfill

  def insert(self, cache_key, paths):
    for cache in self._artifact_caches:  # Insert into all.
      cache.insert(cache_key, paths)

  def has(self, cache_key):
    return any(cache.has(cache_key) for cache in self._artifact_caches)

  def use_cached_files(self, cache_key):
    to_backfill = []
    for cache in self._artifact_caches:
      artifact = cache.use_cached_files(cache_key)
      if not artifact:
        if self._backfill:
          to_backfill.append(cache)
      else:
        paths = list(artifact.get_paths())
        for cache in to_backfill:
          cache.insert(cache_key, paths)
        return artifact
    return None

  def delete(self, cache_key):
    for cache in self._artifact_caches:  # Delete from all.
      cache.delete(cache_key)

  def prune(self, age_hours):
    for cache in self._artifact_caches:
      cache.prune(age_hours)
