# ==================================================================================================
# Copyright 2011 Twitter, Inc.
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

import errno
import hashlib
import os

from abc import ABCMeta, abstractmethod
from collections import namedtuple

from twitter.common.lang import Compatibility
from twitter.pants.base.hash_utils import hash_all


# A CacheKey represents some version of a set of targets.
#  - id identifies the set of targets.
#  - hash is a fingerprint of all invalidating inputs to the build step, i.e., it uniquely determines
#    a given version of the artifacts created when building the target set.
#  - num_sources is the number of source files used to build this version of the target set. Needed only
#    for displaying stats.

CacheKey = namedtuple('CacheKey', ['id', 'hash', 'num_sources'])


class SourceScope(object):
  """Selects sources of a given scope from targets."""

  __metaclass__ = ABCMeta

  @staticmethod
  def for_selector(selector):
    class Scope(SourceScope):
      def select(self, target):
        return selector(target)
    return Scope()

  @abstractmethod
  def select(self, target):
    """Selects source files from the given target and returns them as absolute paths."""

  def valid(self, target):
    """Returns True if the given target can be used with this SourceScope."""
    return hasattr(target, 'expand_files')


NO_SOURCES = SourceScope.for_selector(lambda t: ())
TARGET_SOURCES = SourceScope.for_selector(
  lambda t: t.expand_files(recursive=False, include_buildfile=False)
)
TRANSITIVE_SOURCES = SourceScope.for_selector(
  lambda t: t.expand_files(recursive=True, include_buildfile=False)
)


class CacheKeyGenerator(object):
  """Generates cache keys for versions of target sets."""

  @staticmethod
  def combine_cache_keys(per_target_cache_keys):
    """Returns a cache key for a set of targets that already have cache keys.

    This operation is 'idempotent' in the sense that if per_target_cache_keys contains a single key
    then that key is returned.

    Note that this operation is commutative but not associative.  We use the term 'combine' rather than
    'merge' or 'union' to remind the user of this. Associativity is not a necessary property, in practice.
    """
    if len(per_target_cache_keys) == 1:
      return per_target_cache_keys[0]
    else:
      cache_keys = sorted(per_target_cache_keys)  # For commutativity.
      # Note that combined_id for a list of targets is the same as Target.identify([targets]),
      # for convenience when debugging, but it doesn't have to be for correctness.
      combined_id = hash_all([cache_key.id for cache_key in cache_keys])
      combined_hash = hash_all([cache_key.hash for cache_key in cache_keys])
      combined_num_sources = reduce(lambda x, y: x + y, [cache_key.num_sources for cache_key in cache_keys], 0)
      return CacheKey(combined_id, combined_hash, combined_num_sources)

  def key_for_target(self, target, sources=TARGET_SOURCES, fingerprint_extra=None):
    """Get a key representing the given target and its sources.

    A key for a set of targets can be created by calling combine_cache_keys()
    on the target's individual cache keys.

    :target: The target to create a CacheKey for.
    :sources: A source scope to select from the target for hashing, defaults to TARGET_SOURCES.
    :fingerprint_extra: A function that accepts a sha hash and updates it with extra fingerprint data.
    """
    if not fingerprint_extra:
      if not sources or not sources.valid(target):
        raise ValueError('A target needs to have at least one of sources or a '
                         'fingerprint_extra function to generate a CacheKey.')
    if not sources:
      sources = NO_SOURCES

    sha = hashlib.sha1()
    srcs = sorted(sources.select(target))
    num_sources = self._sources_hash(sha, srcs)
    if fingerprint_extra:
      fingerprint_extra(sha)
    return CacheKey(target.id, sha.hexdigest(), num_sources)

  def key_for(self, id, sources):
    """Get a cache key representing some id and its associated source files.

    Useful primarily in tests. Normally we use key_for_target().
    """
    sha = hashlib.sha1()
    num_sources = self._sources_hash(sha, sources)
    return CacheKey(id, sha.hexdigest(), num_sources)

  def _walk_paths(self, paths):
    """Recursively walk the given paths.

    :returns: Iterable of (relative_path, absolute_path).
    """
    assert not isinstance(paths, Compatibility.string)
    for path in sorted(paths):
      if os.path.isdir(path):
        for dir_name, _, filenames in sorted(os.walk(path)):
          for filename in filenames:
            filename = os.path.join(dir_name, filename)
            yield os.path.relpath(filename, path), filename
      else:
        yield os.path.basename(path), path

  def _sources_hash(self, sha, paths):
    """Update a SHA1 digest with the content of all files under the given paths.

    :returns: The number of files found under the given paths.
    """
    num_files = 0
    for relative_filename, filename in self._walk_paths(paths):
      with open(filename, "rb") as fd:
        sha.update(Compatibility.to_bytes(relative_filename))
        sha.update(fd.read())
      num_files += 1
    return num_files


# A persistent map from target set to cache key, which is a fingerprint of all
# the inputs to the current version of that target set. That cache key can then be used
# to look up build artifacts in an artifact cache.
class BuildInvalidator(object):
  """Invalidates build targets based on the SHA1 hash of source files and other inputs."""

  VERSION = 0

  def __init__(self, root):
    self._root = os.path.join(root, str(BuildInvalidator.VERSION))
    try:
      os.makedirs(self._root)
    except OSError as e:
      if e.errno != errno.EEXIST:
        raise

  def invalidate(self, cache_key):
    """Invalidates this cache key.

    :param cache_key: A CacheKey object (as returned by BuildInvalidator.key_for().
    """
    sha_file = self._sha_file(cache_key)
    if os.path.exists(sha_file):
      os.unlink(sha_file)

  def needs_update(self, cache_key):
    """Check if the given cached item is invalid.

    :param cache_key: A CacheKey object (as returned by BuildInvalidator.key_for().
    :returns: True if the cached version of the item is out of date.
    """
    cached_sha = self._read_sha(cache_key)
    return cached_sha != cache_key.hash

  def update(self, cache_key):
    """Makes cache_key the valid version of the corresponding target set.

    :param cache_key: A CacheKey object (typically returned by BuildInvalidator.key_for()).
    """
    self._write_sha(cache_key)

  def has_key(self, cache_key):
    return os.path.exists(self._sha_file(cache_key))

  def _sha_file(self, cache_key):
    return os.path.join(self._root, cache_key.id) + '.hash'

  def _write_sha(self, cache_key):
    with open(self._sha_file(cache_key), 'w') as fd:
      fd.write(cache_key.hash)

  def _read_sha(self, cache_key):
    try:
      with open(self._sha_file(cache_key), 'rb') as fd:
        return fd.read().strip()
    except IOError as e:
      if e.errno != errno.ENOENT:
        raise
