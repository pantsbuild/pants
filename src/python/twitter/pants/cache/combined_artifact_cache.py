from twitter.pants.cache.artifact_cache import ArtifactCache


class CombinedArtifactCache(ArtifactCache):
  """An artifact cache that delegates to a list of other caches."""
  def __init__(self, artifact_caches):
    if not artifact_caches:
      raise ValueError('Must provide at least one underlying artifact cache')
    log = artifact_caches[0].log
    artifact_root = artifact_caches[0].artifact_root
    if any(x.artifact_root != artifact_root for x in artifact_caches):
      raise ValueError('Combined artifact caches must all have the same artifact root.')
    ArtifactCache.__init__(self, log, artifact_root)
    self._artifact_caches = artifact_caches

  def insert(self, cache_key, build_artifacts):
    for cache in self._artifact_caches:  # Insert into all.
      cache.insert(cache_key, build_artifacts)

  def has(self, cache_key):
    return any(cache.has(cache_key) for cache in self._artifact_caches)

  def use_cached_files(self, cache_key):
    return any(cache.use_cached_files(cache_key) for cache in self._artifact_caches)

  def delete(self, cache_key):
    for cache in self._artifact_caches:  # Delete from all.
      cache.delete(cache_key)
