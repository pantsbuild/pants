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
from twitter.pants.targets import JarDependency, TargetWithSources
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

    self.cache_key = CacheKeyGenerator.combine_cache_keys(per_target_cache_keys)
    self.num_sources = self.cache_key.num_sources
    self.valid = not cache_manager.needs_update(self.cache_key)
    self.targets = targets


  @staticmethod
  def from_versioned_targets(versioned_targets):
    first_target = versioned_targets[0]
    cache_manager = first_target._cache_manager

    # Quick sanity check; all the versioned targets should have the same cache manager.
    # TODO(ryan): the way VersionedTargets store their own links to a single CacheManager instance feels hacky;
    # see if there's a cleaner way for callers to handle awareness of the CacheManager.
    for versioned_target in versioned_targets:
      if versioned_target._cache_manager != cache_manager:
        raise Exception(
          "Attempting to combine versioned targets %s and %s with different CacheMananger instances: %s and %s" % (
            str(first_target), str(versioned_target), str(cache_manager), str(versioned_target._cache_manager)))

    targets = [ vt.target for vt in versioned_targets ]
    cache_keys = [ vt.cache_key for vt in versioned_targets ]
    return VersionedTargetSet(cache_manager, targets, cache_keys)

  def update(self):
    self._cache_manager.update(self)
    self.valid = True

  def __repr__(self):
    return "VTS(%s. %d)" % (','.join(target.id for target in self.targets), 1 if self.valid else 0)


class VersionedTarget(VersionedTargetSet):
  """This class represents a singleton VersionedTargetSet, and has links to VersionedTargets that the wrapped target
  depends on (after having resolvied through any "alias" targets."""
  def __init__(self, cache_manager, target, cache_key):
    VersionedTargetSet.__init__(self, cache_manager, [ target ], [ cache_key ])
    self.target = target
    self.id = target.id
    self.dependencies = set([])
    if not isinstance(target, TargetWithSources):
      raise Exception("Making VersionedTarget for target %s that doesn't have any sources" % target.id)


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

    # This will be a list of VersionedTargets that correspond to @targets.
    versioned_targets = []

    # This will be a mapping from each target to its corresponding VersionedTarget.
    versioned_targets_by_target = {}

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

      # Create a VersionedTarget corresponding to @target.
      versioned_target = VersionedTarget(self, target, cache_key)

      # Add the new VersionedTarget to the list of computed VersionedTargets.
      versioned_targets.append(versioned_target)

      # Add to the mapping from Targets to VersionedTargets, for use in hooking up VersionedTarget dependencies below.
      versioned_targets_by_target[target] = versioned_target

    # Having created all applicable VersionedTargets, now we build the VersionedTarget dependency graph, looking
    # through targets that don't correspond to VersionedTargets themselves.
    versioned_target_deps_by_target = {}

    def get_versioned_target_deps_for_target(target):
      # For every dependency of @target, we will store its corresponding VersionedTarget here. For dependencies that
      # don't correspond to a VersionedTarget (e.g. pass-through dependency wrappers), we will resolve their actual
      # dependencies and find VersionedTargets for them.
      versioned_target_deps = set([])
      if hasattr(target, 'dependencies'):
        for dep in target.dependencies:
          for dependency in dep.resolve():
            if dependency in versioned_targets_by_target:
              # If there exists a VersionedTarget corresponding to this Target, store it and continue.
              versioned_target_deps.add(versioned_targets_by_target[dependency])
            elif dependency in versioned_target_deps_by_target:
              # Otherwise, see if we've already resolved this dependency to the VersionedTargets it depends on, and use
              # those.
              versioned_target_deps.update(versioned_target_deps_by_target[dependency])
            else:
              # Otherwise, compute the VersionedTargets that correspond to this dependency's dependencies, cache and
              # use the computed result.
              versioned_target_deps_by_target[dependency] = get_versioned_target_deps_for_target(dependency)
              versioned_target_deps.update(versioned_target_deps_by_target[dependency])

      # Return the VersionedTarget dependencies that this target's VersionedTarget should depend on.
      return versioned_target_deps

    # Initialize all VersionedTargets to point to the VersionedTargets they depend on.
    for versioned_target in versioned_targets:
      versioned_target.dependencies = get_versioned_target_deps_for_target(versioned_target.target)

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

    versioned_targets is a list of VersionedTarget objects  [ vt1, vt2, vt3, vt4, vt5, vt6, ...].

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
      current_group.total_sources += vt.num_sources

    def close_current_group():
      if len(current_group.vts) > 0:
        new_vt = VersionedTargetSet.from_versioned_targets(current_group.vts)
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
