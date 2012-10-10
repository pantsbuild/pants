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
from twitter.pants.base.target import Target
from twitter.pants.targets import JarDependency
from twitter.pants.targets.internal import InternalTarget


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
  def __init__(self, cache_key_generator, build_invalidator_dir, targets, invalidate_dependents,
               extra_data, only_externaldeps):
    self._cache_key_generator = cache_key_generator
    self._targets = set(targets)
    self._invalidate_dependents = invalidate_dependents
    self._extra_data = pickle.dumps(extra_data)  # extra_data may be None.
    self._sources = NO_SOURCES if only_externaldeps else TARGET_SOURCES
    self._invalidator = BuildInvalidator(build_invalidator_dir)

  def check(self, targets):
    """Checks whether each of the targets has changed and invalidates it if so.

    Returns a list of VersionedTargetSets, one per input target, regardless of whether
    it was invalidated or not. Note that the returned list is in topologically-sorted order.
    That is, if B depends on A then B is later than A.
    """

    # We must check the targets in this order, to ensure correctness if invalidate_dependents=True, since
    # we use earlier cache keys to compute later cache keys in this case.
    ordered_targets = self._order_target_list(targets)
    versioned_targets = []

    # Map from id to current fingerprint of the target with that id. We update this as we iterate, in
    # topological order, so when handling a target, this will already contain all its deps (in this round).
    id_to_hash = {}

    for target in ordered_targets:
      dependency_keys = set()
      if self._invalidate_dependents and hasattr(target, 'dependencies'):
        # Note that we only need to do this for the immediate deps, because those will already
        # reflect changes in their own deps.
        for dep in target.dependencies:
          # We rely on the fact that any deps have already been processed, either in an earlier round or
          # because they came first in ordered_targets.
          if isinstance(dep, Target):
            hash = id_to_hash.get(dep.id, None)
            if hash is None:
              # It may have been processed in a prior round, and therefore the hash should
              # have been written out by the invalidator.
              hash = self._invalidator.existing_hash(dep.id)
              # Note that hash may be None here, indicating that the dependency will not be processed
              # until a later phase. For example, if a codegen target depends on a library target (because
              # the generated code needs that library).
            if hash is not None:
              dependency_keys.add(hash)
          elif isinstance(dep, JarDependency):
            jarid = ''
            for key in CacheManager._JAR_HASH_KEYS:
              jarid += str(getattr(dep, key))
            dependency_keys.add(jarid)
          else:
            dependency_keys.add(str(dep))
          # TODO(John Sirois): Hashing on external targets should have a formal api - we happen to
          # know jars are special and python requirements __str__ works for this purpose.
      cache_key = self._key_for(target, dependency_keys)
      id_to_hash[target.id] = cache_key.hash
      if self._invalidator.needs_update(cache_key):
        self._invalidator.invalidate(cache_key)
        valid = False
      else:
        valid = True
      versioned_targets.append(VersionedTargetSet([target], cache_key, valid))

    return versioned_targets

  def update(self, cache_key):
    """Mark a changed or invalidated target as successfully processed."""
    self._invalidator.update(cache_key)

  def _order_target_list(self, targets):
    """Orders the targets topologically, from least to most dependent."""
    target_ids = set([x.id for x in targets])
    ordered_targets_and_deps = reversed(InternalTarget.sort_targets(targets))
    # Return just the ones that were originally in targets.
    return filter(lambda x: x.id in target_ids, ordered_targets_and_deps)

  def _key_for(self, target, dependency_keys):
    def fingerprint_extra(sha):
      sha.update(self._extra_data)
      for key in dependency_keys:
        sha.update(key)

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

