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

from twitter.pants.base.artifact_cache import create_artifact_cache
from twitter.pants.base.build_invalidator import CacheKeyGenerator
from twitter.pants.tasks.cache_manager import CacheManager, VersionedTargetSet


class TaskError(Exception):
  """Raised to indicate a task has failed."""

class InvalidationResult(object):
  """
    An InvalidationResult represents the result of invalidating a set of targets.

    A task can get individual target info for use in non-flat compiles, or combined info for
    all invalid tasks or all tasks, for flat compiles.
  """
  def __init__(self, cache_manager, all_versioned_targets):
    def combine_versioned_targets(vts):
      targets = []
      for vt in vts:
        targets.extend(vt.targets)
      cache_key = CacheKeyGenerator.combine_cache_keys([vt.cache_key for vt in vts])
      valid = all([vt.valid for vt in vts])
      return VersionedTargetSet(targets, cache_key, valid)

    self._cache_manager = cache_manager
    self._all_versioned_targets = all_versioned_targets
    self._combined_all_versioned_targets = combine_versioned_targets(self._all_versioned_targets)

    self._invalid_versioned_targets = filter(lambda x: not x.valid, all_versioned_targets)
    self._combined_invalid_versioned_targets = combine_versioned_targets(self._invalid_versioned_targets)

  def all_versioned_targets(self):
    """A list of VersionedTargetSet objects, one per target.

    Targets are in topological order, that is if B depends on A then B comes after A in the list.
    """
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
    """A list of all underlying targets, in topological order."""
    return self._combined_all_versioned_targets.targets

  def invalid_targets(self):
    """A list of all underlying targets that are invalid, in topological order."""
    return self._combined_invalid_versioned_targets.targets

  def has_invalid_targets(self):
    """Whether at least one of the targets in this result are invalid."""
    return len(self._combined_invalid_versioned_targets.targets) > 0

  def update_versioned_target(self, vt):
    """Subclasses may call this when building target-by-target, to mark partial progress as valid.

    This is useful so that a failure on a later target doesn't require the earlier targets to be rebuilt."""
    self._cache_manager.update(vt.cache_key)


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
    self._artifact_cache = None
    self._build_invalidator_dir = os.path.join(context.config.get('tasks', 'build_invalidator'), self.product_type())

  def setup_artifact_cache(self, spec):
    """
      Subclasses can call this in their __init__ method to set up artifact caching for that task type.

      spec should be a list of urls/file path prefixes, which are used in that order.
      By default, no artifact caching is used. Subclasses must not only set up the cache, but check it
      explicitly with check_artifact_cache().
    """
    if len(spec) > 0:
      pants_workdir = self.context.config.getdefault('pants_workdir')
      self._artifact_cache = create_artifact_cache(self.context, pants_workdir, spec)

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
      cache is updated for the targets.

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
      targets, invalidate_dependants, extra_data, only_buildfiles)

    # Check for directly changed targets.
    all_versioned_targets = cache_manager.check(targets)
    invalidation_result = InvalidationResult(cache_manager, all_versioned_targets)
    num_invalid_targets = len(invalidation_result.invalid_targets())

    # Do some reporting.
    if num_invalid_targets > 0:
      num_files = reduce(lambda x, y: x + y,
        [vt.cache_key.num_sources for vt in all_versioned_targets if not vt.valid], 0)
      self.context.log.info('Operating on %d files in %d invalidated targets' % (num_files, num_invalid_targets))

    # Yield the result, and then update the cache.
    if num_invalid_targets > 0:
      self.context.log.debug('Invalidated targets %s' % invalidation_result.invalid_targets())
    yield invalidation_result
    for vt in invalidation_result.invalid_versioned_targets():
      cache_manager.update(vt.cache_key)

  @contextmanager
  def check_artifact_cache(self, versioned_targets, build_artifacts):
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
      :build_artifacts a list of paths to which the artifacts will be written. These must be under pants_workdir.
      :returns: False if the caller must build the artifacts, True otherwise.
    """
    if self._artifact_cache is None:
      yield False
      return
    artifact_key = versioned_targets.cache_key
    targets = versioned_targets.targets
    using_cached = False
    if self.context.options.read_from_artifact_cache:
      if self._artifact_cache.use_cached_files(artifact_key):
        self.context.log.info('Using cached artifacts for %s' % targets)
        using_cached = True
      else:
        self.context.log.info('No cached artifacts for %s' % targets)

    yield using_cached

    if not using_cached and self.context.options.write_to_artifact_cache:
      if self.context.options.verify_artifact_cache:
        pass  # TODO: verification logic
      self.context.log.info('Caching artifacts for %s' % str(targets))
      self._artifact_cache.insert(artifact_key, build_artifacts)



__all__ = (
  'TaskError',
  'Task'
)
