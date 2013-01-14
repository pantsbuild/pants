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

from twitter.pants.base.build_invalidator import BuildInvalidator, CacheKeyGenerator, NO_SOURCES, TARGET_SOURCES
from twitter.pants.base.target import Target
from twitter.pants.targets import JarDependency
from twitter.pants.targets.internal import InternalTarget


# A VersionedTargetSet represents a list of targets, a corresponding CacheKey, and a flag determining
# whether the list of targets is currently valid.
#
#  - When invalidating a single target, this can be used to represent that target as a singleton.
#
#  - When checking the artifact cache, this can also be used to represent a list of targets
#    that are built together into a single artifact.
class VersionedTargetSet(object):
  def __init__(self, cache_manager, targets, per_target_cache_keys):
    self._cache_manager = cache_manager
    self.per_target_cache_keys = per_target_cache_keys

    self.targets = targets
    self.cache_key = CacheKeyGenerator.combine_cache_keys(per_target_cache_keys)
    self.valid = not cache_manager.needs_update(self.cache_key)

  def update(self):
    self._cache_manager.update(self)
    self.valid = True

# The result of calling check() on a CacheManager.
# Each member is a list of VersionedTargetSet objects in topological order.
# Tasks may need to perform no, some or all operations on either of these, depending on how they
# are implemented.
class InvalidationCheck(object):
  def __init__(self, all_vts, all_vts_partitioned, invalid_vts, invalid_vts_partitioned):
    # All the targets, valid and invalid.
    self.all_vts = all_vts

    # All the targets, partitioned if so requested.
    self.all_vts_partitioned = all_vts_partitioned

    # Just the invalid targets.
    self.invalid_vts = invalid_vts

    # Just the invalid targets, partitioned if so requested.
    self.invalid_vts_partitioned = invalid_vts_partitioned

class CacheManager(object):
  """Manages cache checks, updates and invalidation keeping track of basic change
  and invalidation statistics.
  """
  def __init__(self, cache_key_generator, build_invalidator_dir,
               invalidate_dependents, extra_data, only_externaldeps):
    self._cache_key_generator = cache_key_generator
    self._invalidate_dependents = invalidate_dependents
    self._extra_data = pickle.dumps(extra_data)  # extra_data may be None.
    self._sources = NO_SOURCES if only_externaldeps else TARGET_SOURCES

    self._invalidator = BuildInvalidator(build_invalidator_dir)

  def update(self, vts):
    """Mark a changed or invalidated VersionedTargetSet as successfully processed."""
    for cache_key in vts.per_target_cache_keys:
      self._invalidator.update(cache_key)
    self._invalidator.update(vts.cache_key)

  def check(self, targets, partition_size_hint):
    """Checks whether each of the targets has changed and invalidates it if so.

    Returns a list of VersionedTargetSet objects (either valid or invalid). The returned sets 'cover'
    the input targets, possibly partitioning them, and are in topological order.
    The caller can inspect these in order and, e.g., rebuild the invalid ones.
    """
    all_vts = self._sort_and_validate_targets(targets)
    invalid_vts = filter(lambda vt: not vt.valid, all_vts)
    all_vts_partitioned = self._partition_versioned_targets(all_vts, partition_size_hint)
    invalid_vts_partitioned = self._partition_versioned_targets(invalid_vts, partition_size_hint)
    return InvalidationCheck(all_vts, all_vts_partitioned, invalid_vts, invalid_vts_partitioned)

  def _sort_and_validate_targets(self, targets):
    """Validate each target.

    Returns a topologically ordered set of VersionedTargets, each representing one input target.
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
      versioned_targets.append(VersionedTargetSet(self, [target], [cache_key]))

    return versioned_targets

  def needs_update(self, cache_key):
    return self._invalidator.needs_update(cache_key)

  def _order_target_list(self, targets):
    """Orders the targets topologically, from least to most dependent."""
    target_ids = set([x.id for x in targets])

    # Most to least dependent.
    reverse_ordered_targets_and_deps = InternalTarget.sort_targets(targets)
    # Least to most dependent. We must build in this order.
    ordered_targets_and_deps = reversed(reverse_ordered_targets_and_deps)
    # Return just the ones that were originally in targets.
    return filter(lambda x: x.id in target_ids, ordered_targets_and_deps)

  def _partition_versioned_targets(self, versioned_targets, partition_size_hint):
    """Groups versioned targets so that each group has roughly the same number of sources.

    versioned_targets is a list of VersionedTargetSet objects  [ vt1, vt2, vt3, vt4, vt5, vt6, ...].

    Returns a list of VersionedTargetSet objects, e.g., [ VT1, VT2, VT3, ...] representing the
    same underlying targets. E.g., VT1 is the combination of [vt1, vt2, vt3], VT2 is the combination
    of [vt4, vt5] and VT3 is [vt6].

    The new versioned targets are chosen to have roughly partition_size_hint sources.

    This is useful as a compromise between flat mode, where we build all targets in a
    single compiler invocation, and non-flat mode, where we invoke a compiler for each target,
    which may lead to lots of compiler startup overhead. A task can choose instead to build one
    group at a time.
    """
    res = []

    # Hack around the python outer scope problem.
    class VtGroup(object):
      def __init__(self):
        self.vts = []
        self.total_sources = 0

    current_group = VtGroup()

    def add_to_current_group(vt):
      current_group.vts.append(vt)
      current_group.total_sources += vt.cache_key.num_sources

    def close_current_group():
      if len(current_group.vts) > 0:
        new_vt = self._combine_versioned_targets(current_group.vts)
        res.append(new_vt)
        current_group.vts = []
        current_group.total_sources = 0

    for vt in versioned_targets:
      add_to_current_group(vt)
      if current_group.total_sources > partition_size_hint:
        if current_group.total_sources > 1.5 * partition_size_hint and len(current_group.vts) > 1:
          # Too big. Close the current group without this vt and add it to the next one.
          current_group.vts.pop()
          close_current_group()
          add_to_current_group(vt)
        else:
          close_current_group()
    close_current_group()  # Close the last group, if any.

    return res

  def _combine_versioned_targets(self, vts):
    targets = []
    for vt in vts:
      targets.extend(vt.targets)
    return VersionedTargetSet(self, targets, [vt.cache_key for vt in vts])

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
    '_configurations',
    'artifacts'
    )
