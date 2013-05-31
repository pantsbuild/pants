import os
import shutil
from twitter.common.dirutil import safe_mkdir, safe_rmtree
from twitter.pants.cache.artifact_cache import ArtifactCache


class FileBasedArtifactCache(ArtifactCache):
  """An artifact cache that stores the artifacts in local files."""
  def __init__(self, log, artifact_root, cache_root, copy_fn=None):
    """
    cache_root: The locally cached files are stored under this directory.
    copy_fn: An optional function with the signature copy_fn(absolute_src_path, relative_dst_path) that
        will copy cached files into the desired destination. If unspecified, a simple file copy is used.
    """
    ArtifactCache.__init__(self, log, artifact_root)
    self._cache_root = cache_root
    self._copy_fn = copy_fn or (
      lambda src, rel_dst: shutil.copy(src, os.path.join(self.artifact_root, rel_dst)))
    safe_mkdir(self._cache_root)

  def try_insert(self, cache_key, build_artifacts):
    cache_dir = self._cache_dir_for_key(cache_key)
    safe_rmtree(cache_dir)
    for artifact in build_artifacts or ():
      rel_path = os.path.relpath(artifact, self.artifact_root)

      if rel_path.startswith('..'):
        raise self.CacheError('Artifact %s is not under artifact root %s' % (artifact,
                                                                             self.artifact_root))

      artifact_dest = os.path.join(cache_dir, rel_path)
      safe_mkdir(os.path.dirname(artifact_dest))
      if os.path.isdir(artifact):
        shutil.copytree(artifact, artifact_dest)
      else:
        shutil.copy(artifact, artifact_dest)

  def has(self, cache_key):
    return os.path.isdir(self._cache_dir_for_key(cache_key))

  def use_cached_files(self, cache_key):
    cache_dir = self._cache_dir_for_key(cache_key)
    if not os.path.exists(cache_dir):
      return False
    for dir_name, _, filenames in os.walk(cache_dir):
      for filename in filenames:
        filename = os.path.join(dir_name, filename)
        relative_filename = os.path.relpath(filename, cache_dir)
        self._copy_fn(filename, relative_filename)
    return True

  def delete(self, cache_key):
    safe_rmtree(self._cache_dir_for_key(cache_key))

  def _cache_dir_for_key(self, cache_key):
    # Note: it's important to use the id as well as the hash, because two different targets
    # may have the same hash if both have no sources, but we may still want to differentiate them.
    return os.path.join(self._cache_root, cache_key.id, cache_key.hash)
