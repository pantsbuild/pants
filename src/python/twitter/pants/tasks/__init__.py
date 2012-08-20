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

from contextlib import contextmanager
import hashlib
import os
import shutil

from twitter.pants.base.artifact_cache import ArtifactCache
from twitter.pants.base.build_invalidator import CacheKeyGenerator
from twitter.pants.tasks.cache_manager import CacheManager, VersionedTargetSet


class TaskError(Exception):
  """Raised to indicate a task has failed."""


class TargetError(TaskError):
  """Raised to indicate a task has failed for a subset of targets"""
  def __init__(self, targets, *args, **kwargs):
    TaskError.__init__(self, *args, **kwargs)
    self.targets = targets


class InvalidationResult(object):
  """
    An InvalidationResult represents the result of invalidating a set of targets.

    A task can get individual target info for use in non-flat compiles, or combined info for
    all invalid tasks or all tasks, for flat compiles.
  """
  def __init__(self, all_versioned_targets):
    def combine_versioned_targets(vts):
      targets = []
      for vt in vts:
        targets.extend(vt.targets)
      cache_key = CacheKeyGenerator.combine_cache_keys([vt.cache_key for vt in vts])
      valid = all([vt.valid for vt in vts])
      return VersionedTargetSet(targets, cache_key, valid)

    self._all_versioned_targets = all_versioned_targets
    self._combined_all_versioned_targets = combine_versioned_targets(self._all_versioned_targets)

    self._invalid_versioned_targets = filter(lambda x: not x.valid, all_versioned_targets)
    self._combined_invalid_versioned_targets = combine_versioned_targets(self._invalid_versioned_targets)

  def all_versioned_targets(self):
    """A list of VersionedTargetSet objects, one per target."""
    return self._all_versioned_targets

  def combined_all_versioned_targets(self):
    """A single VersionedTargetSet representing all targets together."""
    return self._combined_all_versioned_targets

  def invalid_versioned_targets(self):
    """A list of VersionedTargetSet objects, one per invalid target."""
    return self._invalid_versioned_targets

  def combined_invalid_versioned_targets(self):
    """A single VersionedTargetSet representing all invalid targets together."""
    return self._combined_invalid_versioned_targets

  def all_targets(self):
    """A list of all underlying targets."""
    return self._combined_all_versioned_targets.targets

  def invalid_targets(self):
    """A list of all underlying targets that are invalid."""
    return self._combined_invalid_versioned_targets.targets

  def has_invalid_targets(self):
    """Whether at least one of the targets in this result are invalid."""
    return len(self._combined_invalid_versioned_targets.targets) > 0


class Task(object):
  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    """
      Subclasses can add flags to the pants command line using the given option group.  Flag names
      should be created with mkflag([name]) to ensure flags are properly namespaced amongst other
      tasks.
    """

  def __init__(self, context):
    self.context = context
    self._cache_key_generator = CacheKeyGenerator()
    # TODO: Shared, remote build cache.
    self._artifact_cache = ArtifactCache(context.config.get('tasks', 'artifact_cache'))
    self._build_invalidator_dir = os.path.join(context.config.get('tasks', 'build_invalidator'), self.product_type())

  def product_type(self):
    """
      By default, each task is considered as creating a unique product type.
      Subclasses can override this to specify a shared product type, e.g., 'classes'.

      Tasks with the same product type can invalidate each other's targets, e.g., if a ScalaLibrary
      depends on a JavaLibrary, a change to the JavaLibrary will invalidated the ScalaLibrary because
      they both have the same product type.
    """
    return self.__class__.__name__

  def execute(self, targets):
    """
      Executes this task against the given targets which may be a subset of the current context
      targets.
    """

  def invalidate_for(self):
    """
      Subclasses can override and return an object that should be checked for changes when
      managing target invalidation.  If the pickled form of returned object changes
      between runs all targets will be invalidated.
    """
    return None

  def invalidate_for_files(self):
    """
      Subclasses can override and return a list of full paths to extra, non-source files that should
      be checked for changes when managing target invalidation. This is useful for tracking
      changes to pre-built build tools, e.g., the thrift compiler.
    """
    return []

  @contextmanager
  def invalidated(self, targets, only_buildfiles=False, invalidate_dependants=False):
    """
      Checks targets for invalidation.

      Yields the result to a with block. If no exceptions are thrown by work in the block, the
      cache is updated for the targets, otherwise if a TargetError is thrown by the work in the
      block all targets except those in the TargetError are cached.

      :targets The targets to check for changes.
      :only_buildfiles If True, then just the target's BUILD files are checked for changes.
      :invalidate_dependants If True then any targets depending on changed targets are invalidated.
      :returns: an InvalidationResult reflecting the invalidated targets.
    """
    # invalidate_for() may return an iterable that isn't a set, so we ensure a set here.
    extra_data = []
    extra_data.append(self.invalidate_for())

    for f in self.invalidate_for_files():
      sha = hashlib.sha1()
      with open(f, "rb") as fd:
        sha.update(fd.read())
      extra_data.append(sha.hexdigest())

    cache_manager = CacheManager(self._cache_key_generator, self._build_invalidator_dir,
      targets, extra_data, only_buildfiles)

    # Check for directly changed targets.
    all_versioned_targets = [ cache_manager.check(target) for target in targets ]
    directly_changed_targets = set(vt.targets[0] for vt in all_versioned_targets if not vt.valid)
    versioned_targets_by_target = dict([(vt.targets[0], vt) for vt in all_versioned_targets])

    # Now add any extra targets we need to invalidate.
    if invalidate_dependants:
      for target in (self.context.dependants(lambda t: t in directly_changed_targets)).keys():
        if target in versioned_targets_by_target:
          vt = versioned_targets_by_target.get(target)
          cache_key = vt.cache_key
          vt.valid = False
        else:  # The target isn't in targets (it belongs to a future round).
          cache_key = None
        cache_manager.invalidate(target, cache_key)

    # Now we're done with invalidation, so can create the result.
    invalidation_result = InvalidationResult(all_versioned_targets)
    num_invalid_targets = len(invalidation_result.invalid_targets())

    # Do some reporting.
    if cache_manager.foreign_invalidated_targets:
      self.context.log.info('Invalidated %d dependent targets '
                            'for the next round' % cache_manager.foreign_invalidated_targets)

    if cache_manager.changed_files:
      msg = 'Operating on %d files in %d changed targets' % (
        cache_manager.changed_files,
        cache_manager.changed_targets,
      )
      if cache_manager.invalidated_files:
        msg += ' and %d files in %d invalidated dependent targets' % (
          cache_manager.invalidated_files,
          cache_manager.invalidated_targets
        )
      self.context.log.info(msg)

    # Yield the result, and then update the cache.
    try:
      if num_invalid_targets > 0:
        self.context.log.debug('Invalidated targets %s' % invalidation_result.invalid_targets())
      yield invalidation_result
      for vt in invalidation_result.invalid_versioned_targets():
        cache_manager.update(vt.cache_key)

    except TargetError as e:
      # TODO: This partial updating isn't used (yet?). Nowhere in the code do we raise a TargetError.
      for vt in invalidation_result.invalid_versioned_targets():
        if len(vt.targets) != 1:
          raise Exception, 'Logic error: vt should represent a single target'
        if vt.targets[0] not in e.targets:
          cache_manager.update(vt.cache_key)

  @contextmanager
  def check_artifact_cache(self, versioned_targets, build_artifacts, artifact_root):
    """
      See if we have required artifacts in the cache.

      If we do (and reading from the artifact cache is enabled) then we copy the artifacts from the cache.
      If we don't (and writing to the artifact cache is enabled) then we will copy the artifacts into
      the cache when the context is exited.

      Therefore the usage idiom is as follows:

      with self.check_artifact_cache(...) as build:
        if build:
          ... build the necessary artifacts ...

      :versioned_targets a VersionedTargetSet representing a specific version of a set of targets.
      :build_artifacts a list of paths to which the artifacts will be written.
      :artifact_root If not None, the artifact paths will be cached relative to this dir.
      :returns: True if the caller must build the artifacts, False otherwise.
    """
    artifact_key = versioned_targets.cache_key
    targets = versioned_targets.targets
    if self.context.options.read_from_artifact_cache and self._artifact_cache.has(artifact_key):
      self.context.log.info('Using cached artifacts for %s' % targets)
      self._artifact_cache.use_cached_files(artifact_key,
        lambda src, reldest: shutil.copy(src, os.path.join(artifact_root, reldest)))
      yield False  # Caller need not rebuild
    else:
      self.context.log.info('No cached artifacts for %s' % targets)
      yield True  # Caller must rebuild.

      if self.context.options.write_to_artifact_cache:
        if self._artifact_cache.has(artifact_key):
          # If we get here it means read_from_artifact_cache is false, so we've rebuilt.
          # We can verify that what we built is identical to the cached version.
          # If not, there's a dangerous bug, so we want to warn about this loudly.
          if self.context.options.verify_artifact_cache:
            pass  # TODO: verification logic
        else:
          # if the caller provided paths to artifacts but we didn't previously have them in the cache,
          # we assume that they are now created, and store them in the artifact cache.
          self.context.log.info('Caching artifacts for %s' % str(targets))
          self._artifact_cache.insert(artifact_key, build_artifacts, artifact_root)

__all__ = (
  'TaskError',
  'TargetError',
  'Task'
)
