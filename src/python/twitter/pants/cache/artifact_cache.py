import os

# Note throughout the distinction between the artifact_root (which is where the artifacts are
# originally built and where the cache restores them to) and the cache root path/URL (which is
# where the artifacts are cached).


class ArtifactCache(object):
  """A map from cache key to a set of build artifacts.

  The cache key must uniquely identify the inputs (sources, compiler flags etc.) needed to
  build the artifacts. Cache keys are typically obtained from a CacheKeyGenerator.

  Subclasses implement the methods below to provide this functionality.
  """

  class CacheError(Exception):
    """Indicates a problem writing to or reading from the cache."""

  def __init__(self, context, artifact_root):
    """Create an ArtifactCache.

    All artifacts must be under artifact_root.
    """
    self.context = context
    self.artifact_root = artifact_root

  def insert(self, cache_key, build_artifacts):
    """Cache the output of a build.

    If there is an existing set of artifacts for this key they are deleted.

    TODO: Check that they're equal? If they aren't it's a grave bug, since the key is supposed
    to be a fingerprint of all possible inputs to the build.

    cache_key: A CacheKey object.
    build_artifacts: List of paths to generated artifacts. These must be under pants_workdir.
    """
    # It's OK for artifacts not to exist- we assume that the build didn't need to create them
    # in this case (e.g., a no-op build on an empty target).
    build_artifacts_that_exist = filter(lambda f: os.path.exists(f), build_artifacts)
    try:
      self.try_insert(cache_key, build_artifacts_that_exist)
    except Exception as e:
      try:
        err_msg = 'Error while writing to artifact cache: %s. Deleting, just in case.' % e
        if self.context:
          self.context.log.error(err_msg)
        else:
          print(err_msg)
        self.delete(cache_key)
      except Exception:
        print('IMPORTANT: failed to delete %s on error. Your artifact cache may be corrupted. '
              'Please delete manually.' % cache_key.id)

  def try_insert(self, cache_key, build_artifacts):
    """Attempt to cache the output of a build, without error-handling.

    If there is an existing set of artifacts for this key they are deleted.

    cache_key: A CacheKey object.
    build_artifacts: List of paths to generated artifacts. These must be under pants_workdir.
    """
    pass

  def has(self, cache_key):
    pass

  def use_cached_files(self, cache_key):
    """Use the artifacts cached for the given key.

    Returns True if files were found and used, False otherwise.

    cache_key: A CacheKey object.
    """
    pass

  def delete(self, cache_key):
    """Delete the artifacts for the specified key.

    Deleting non-existent artifacts is a no-op.
    """
    pass


