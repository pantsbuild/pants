from twitter.common.dirutil import safe_delete
from twitter.pants.cache.artifact_cache import ArtifactCache


class TransformingArtifactCache(ArtifactCache):
  """An artifact cache that transforms the artifacts of another cache."""
  def __init__(self, cache, pre_write_func=None, post_read_func=None):
    """
    cache: The underlying artifact cache.
    """
    ArtifactCache.__init__(self, cache.log, cache.artifact_root, cache.read_only)
    self._cache = cache
    self._pre_write_func = pre_write_func
    self._post_read_func = post_read_func

  def insert(self, cache_key, paths):
    if self._pre_write_func:
      paths = self._pre_write_func(paths)  # Can return None to signal not to cache.
    if paths is not None:
      self._cache.insert(cache_key, paths)

  def has(self, cache_key):
    return self._cache.has(cache_key)

  def use_cached_files(self, cache_key):
    artifact = self._cache.use_cached_files(cache_key)
    if artifact and self._post_read_func:
      paths = artifact.get_paths()
      new_paths = self._post_read_func(paths)  # Can return None to signal failure.
      if new_paths is None:  # Failure. Delete artifact and pretend it was never found.
        for path in paths:
          safe_delete(path)
        self.delete(cache_key)
        artifact = None
      else:
        artifact.override_paths(new_paths)
    return artifact

  def delete(self, cache_key):
    self._cache.delete(cache_key)

  def prune(self, age_hours):
    self._cache.prune(age_hours)
