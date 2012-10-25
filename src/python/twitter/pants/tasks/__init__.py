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
import sys

from twitter.pants.base.artifact_cache import create_artifact_cache
from twitter.pants.base.build_invalidator import CacheKeyGenerator
from twitter.pants.tasks.cache_manager import CacheManager


class TaskError(Exception):
  """Raised to indicate a task has failed."""


class Task(object):
  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    """Set up the cmd-line parser.

    Subclasses can add flags to the pants command line using the given option group.  Flag names
    should be created with mkflag([name]) to ensure flags are properly namespaced amongst other tasks.
    """

  def __init__(self, context):
    self.context = context
    self.dry_run = self.can_dry_run() and self.context.options.dry_run
    self._cache_key_generator = CacheKeyGenerator()
    self._artifact_cache = None
    self._build_invalidator_dir = os.path.join(context.config.get('tasks', 'build_invalidator'), self.product_type())

  def setup_artifact_cache(self, spec):
    """Subclasses can call this in their __init__ method to set up artifact caching for that task type.

    spec should be a list of urls/file path prefixes, which are used in that order.
    By default, no artifact caching is used. Subclasses must not only set up the cache, but check it
    explicitly with check_artifact_cache().
    """
    if len(spec) > 0:
      pants_workdir = self.context.config.getdefault('pants_workdir')
      self._artifact_cache = create_artifact_cache(self.context, pants_workdir, spec)

  def product_type(self):
    """Set the product type for this task.

    By default, each task is considered as creating a unique product type.
    Subclasses can override this to specify a shared product type, e.g., 'classes'.

    Tasks with the same product type can invalidate each other's targets, e.g., if a ScalaLibrary
    depends on a JavaLibrary, a change to the JavaLibrary will invalidate the ScalaLibrary because
    they both have the same product type.
    """
    return self.__class__.__name__

  def can_dry_run(self):
    """Subclasses can override this to indicate that they respect the --dry-run flag.

    It's the subclass task's responsibility to do the right thing if this flag is set.

    Note that tasks such as codegen and ivy resolution cannot dry-run, because subsequent
    cache key computation will fail on missing sources/external deps.
    """
    return False

  def execute(self, targets):
    """Executes this task against the given targets which may be a subset of the current context targets."""
    raise TaskError('execute() not implemented')

  def invalidate_for(self):
    """Provides extra objects that participate in invalidation.

    Subclasses can override and return an object that should be checked for changes when
    managing target invalidation.  If the pickled form of returned object changes
    between runs all targets will be invalidated.
    """
    return None

  def invalidate_for_files(self):
    """Provides extra files that participate in invalidation.

    Subclasses can override and return a list of full paths to extra, non-source files that should
    be checked for changes when managing target invalidation. This is useful for tracking
    changes to pre-built build tools, e.g., the thrift compiler.
    """
    return []

  @contextmanager
  def invalidated(self, targets, only_buildfiles=False, invalidate_dependants=False,
                  partition_size_hint=sys.maxint):
    """Checks targets for invalidation. Subclasses call this to figure out what to work on.

    targets: The targets to check for changes.

    only_buildfiles: If True, then only the target's BUILD files are checked for changes, not its sources.

    invalidate_dependants: If True then any targets depending on changed targets are invalidated.

    partition_size_hint: Each VersionedTargetSet in the yielded list will represent targets containing roughly
    this number of source files, if possible. Set to sys.maxint for a single VersionedTargetSet. Set to 0 for
    one VersionedTargetSet per target. It is up to the caller to do the right thing with whatever partitioning
    it asks for.

    Yields an InvalidationCheck object reflecting the (partitioned) targets. If no exceptions are
    thrown by work in the block, the cache is updated for the targets.
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
      invalidate_dependants, extra_data, only_buildfiles)

    invalidation_check = cache_manager.check(targets, partition_size_hint)

    num_invalid_partitions = len(invalidation_check.invalid_vts_partitioned)
    num_invalid_targets = 0
    num_invalid_sources = 0
    for vt in invalidation_check.invalid_vts:
      if not vt.valid:
        num_invalid_targets += len(vt.targets)
        num_invalid_sources += vt.cache_key.num_sources

    # Do some reporting.
    if num_invalid_partitions > 0:
      self.context.log.info('Operating on %d files in %d invalidated targets in %d target partitions' % \
                            (num_invalid_sources, num_invalid_targets, num_invalid_partitions))

    # Yield the result, and then update the cache.
    yield invalidation_check
    if not self.dry_run:
      for vt in invalidation_check.invalid_vts:
        vt.update()  # In case the caller doesn't update.

  @contextmanager
  def check_artifact_cache(self, versioned_targets, build_artifacts):
    """See if we have required artifacts in the cache.

    If we do (and reading from the artifact cache is enabled) then we copy the artifacts from the cache.
    If we don't (and writing to the artifact cache is enabled) then we will copy the artifacts into
    the cache when the context is exited.

    Therefore the usage idiom is as follows:

    with self.check_artifact_cache(...) as in_cache:
      if not in_cache:
        ... build the necessary artifacts ...

    versioned_targets: a VersionedTargetSet representing a specific version of a set of targets.

    build_artifacts: a list of paths to which the artifacts will be written. These must be under pants_workdir.

    Returns False if the caller must build the artifacts, True otherwise.
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
