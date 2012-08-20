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

try:
  import cPickle as pickle
except ImportError:
  import pickle

from twitter.common.collections import OrderedSet
from twitter.pants.base.build_invalidator import BuildInvalidator, NO_SOURCES, TARGET_SOURCES
from twitter.pants.targets import JarDependency


# A VersionedTargetSet represents a list of targets, a corresponding CacheKey, and a flag determining
# whether the list of targets is currently valid.
#
#  - When invalidating a single target, this can be used to represent that target as a singleton.
#
#  - When checking the artifact cache, this can also be used to represent a list of targets
#    that are built together into a single artifact (e.g., when building Java in 'flat mode').
class VersionedTargetSet(object):
  def __init__(self, targets, cache_key, valid):
    self.targets = targets
    self.cache_key = cache_key
    self.valid = valid


class CacheManager(object):
  """
    Manages cache checks, updates and invalidation keeping track of basic change
    and invalidation statistics.
  """
  def __init__(self, cache_key_generator, build_invalidator_dir, targets, extra_data, only_externaldeps):
    self._cache_key_generator = cache_key_generator
    self._targets = set(targets)
    self._extra_data = pickle.dumps(extra_data)  # extra_data may be None.
    self._sources = NO_SOURCES if only_externaldeps else TARGET_SOURCES
    self._invalidator = BuildInvalidator(build_invalidator_dir)

    # Counts, purely for display purposes.
    self.changed_files = 0
    self.changed_targets = 0
    self.invalidated_files = 0
    self.invalidated_targets = 0
    self.foreign_invalidated_targets = 0

  def check(self, target):
    """Checks if a target has changed and invalidates it if so.

    Returns a VersionedTargetSet for the target, regardless of whether it was invalidated or not.
    """
    cache_key = self._key_for(target)
    if cache_key and self._invalidator.needs_update(cache_key):
      self._invalidate(target, cache_key)
      valid = False
    else:
      valid = True
    ret = VersionedTargetSet([target], cache_key, valid)
    return ret

  def update(self, cache_key):
    """Mark a changed or invalidated target as successfully processed."""
    self._invalidator.update(cache_key)

  def invalidate(self, target, cache_key=None):
    """Forcibly mark a target as changed.

    If cache_key is unspecified, computes it. As an optimization, caller can specify the
    cache key if it knows it, to prevent needless recomputation.
    """
    if cache_key is None:
      cache_key = self._key_for(target)
    self._invalidate(target, cache_key, indirect=True)

  def _key_for(self, target):
    def fingerprint_extra(sha):
      sha.update(self._extra_data)
      self._fingerprint_jardeps(target, sha)

    return self._cache_key_generator.key_for_target(
      target,
      sources=self._sources,
      fingerprint_extra=fingerprint_extra
    )

  _JAR_HASH_KEYS = (
    'org',
    'name',
    'rev',
    'force',
    'excludes',
    'transitive',
    'ext',
    'url',
    '_configurations'
    )

  def _fingerprint_jardeps(self, target, sha):
    internaltargets = OrderedSet()
    alltargets = OrderedSet()
    def fingerprint_external(target):
      internaltargets.add(target)
      if hasattr(target, 'dependencies'):
        alltargets.update(target.dependencies)
    target.walk(fingerprint_external)

    for external_target in alltargets - internaltargets:
      # TODO(John Sirois): Hashing on external targets should have a formal api - we happen to
      # know jars are special and python requirements __str__ works for this purpose.
      if isinstance(external_target, JarDependency):
        jarid = ''
        for key in CacheManager._JAR_HASH_KEYS:
          jarid += str(getattr(external_target, key))
        sha.update(jarid)
      else:
        sha.update(str(external_target))

  def _invalidate(self, target, cache_key, indirect=False):
    self._invalidator.invalidate(cache_key)
    if target in self._targets:
      if indirect:
        self.invalidated_files += cache_key.num_sources
        self.invalidated_targets += 1
      else:
        self.changed_files += cache_key.num_sources
        self.changed_targets += 1
    else:
      # invalidate a target to be processed in a subsequent round - this handles goal groups
      self.foreign_invalidated_targets += 1
