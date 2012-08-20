# ==================================================================================================
# Copyright 2012 Twitter, Inc.
# --------------------------------------------------------------------------------------------------
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this work except in compliance with the License.
# You may obtain a copy of the License in the LICENSE file, or at:
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==================================================================================================

import os
import shutil

from twitter.common.dirutil import safe_mkdir, safe_rmtree


class ArtifactCache(object):
  """
    A map from cache key to a set of build artifacts.

    The cache key must uniquely identify the inputs (sources, compiler flags etc.) needed to
    build the artifacts. Cache keys are typically obtained from a CacheKeyGenerator.
  """
  def __init__(self, root):
    self._root = root
    safe_mkdir(self._root)

  def insert(self, cache_key, build_artifacts, artifact_root=None):
    """Cache the output of a build.

    If there is an existing set of artifacts for this key they are deleted.

    TODO: Check that they're equal? If they aren't it's a grave bug, since the key is supposed
    to be a fingerprint of all possible inputs to the build.

    :param cache_key: A CacheKey object.
    :param build_artifacts: List of paths to generated artifacts under artifact_root.
    :param artifact_root: Optional root directory under which artifacts are stored.
    """
    cache_dir = self._cache_dir_for_key(cache_key)
    try:
      safe_rmtree(cache_dir)
      for artifact in build_artifacts or ():
        rel_path = os.path.basename(artifact) \
        if artifact_root is None \
        else os.path.relpath(artifact, artifact_root)
        assert not rel_path.startswith('..'), \
          'Weird: artifact=%s, rel_path=%s' % (artifact, rel_path)
        artifact_dest = os.path.join(cache_dir, rel_path)
        dir_name = os.path.dirname(artifact_dest)
        safe_mkdir(dir_name)
        if os.path.isdir(artifact):
          shutil.copytree(artifact, artifact_dest)
        else:
          shutil.copy(artifact, artifact_dest)
    except Exception as e:
      try:
        safe_rmtree(cache_dir)
      except Exception as e:
        print('IMPORTANT: failed to delete %s on error. Your artifact cache may be corrupted. '
              'Please delete manually.' % cache_dir)
      raise e

  def has(self, cache_key):
    return os.path.isdir(self._cache_dir_for_key(cache_key))

  def use_cached_files(self, cache_key, copy_fn):
    """Use cached files, typically by hard-linking them from the cache into a staging area.

    :param cache_key: A CacheKey object.
    :param copy_fn: A function with the signature copy_fn(absolute_src_path, relative_dst_path) that
        will copy cached files into the desired destination.
    """
    cache_dir = self._cache_dir_for_key(cache_key)
    for dir_name, _, filenames in os.walk(cache_dir):
      for filename in filenames:
        filename = os.path.join(dir_name, filename)
        relative_filename = os.path.relpath(filename, cache_dir)
        copy_fn(filename, relative_filename)

  def _cache_dir_for_key(self, cache_key):
    return os.path.join(self._root, cache_key.hash)
