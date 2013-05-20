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

import itertools
import os
import sys

from contextlib import contextmanager
from multiprocessing.pool import ThreadPool

from twitter.common.collections.orderedset import OrderedSet

from twitter.pants.base.artifact_cache import create_artifact_cache
from twitter.pants.base.hash_utils import hash_file
from twitter.pants.base.build_invalidator import CacheKeyGenerator
from twitter.pants.reporting.reporting_utils import items_to_report_element
from twitter.pants.tasks.cache_manager import CacheManager, InvalidationCheck


class TaskError(Exception):
  """Raised to indicate a task has failed."""


class Task(object):
  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    """Set up the cmd-line parser.

    Subclasses can add flags to the pants command line using the given option group.
    Flag names should be created with mkflag([name]) to ensure flags are properly namespaced
    amongst other tasks.
    """

  def __init__(self, context):
    self.context = context
    self.dry_run = self.can_dry_run() and self.context.options.dry_run
    self._cache_key_generator = CacheKeyGenerator()
    self._artifact_cache = None
    self._build_invalidator_dir = os.path.join(context.config.get('tasks', 'build_invalidator'),
                                               self.product_type())

  def setup_artifact_cache(self, spec):
    """Subclasses can call this in their __init__() to set up artifact caching for that task type.

    spec should be a list of urls/file path prefixes, which are used in that order.
    By default, no artifact caching is used.
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
    """Executes this task against targets, which may be a subset of the current context targets."""
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
  def invalidated(self, targets, only_buildfiles=False, invalidate_dependents=False,
                  partition_size_hint=sys.maxint):
    """Checks targets for invalidation. Subclasses call this to figure out what to work on.

    targets:               The targets to check for changes.
    only_buildfiles:       If True, then only the target's BUILD files are checked for changes, not
                           its sources.
    invalidate_dependents: If True then any targets depending on changed targets are invalidated.
    partition_size_hint:   Each VersionedTargetSet in the yielded list will represent targets
                           containing roughly this number of source files, if possible. Set to
                           sys.maxint for a single VersionedTargetSet. Set to 0 for one
                           VersionedTargetSet per target. It is up to the caller to do the right
                           thing with whatever partitioning it asks for.

    Yields an InvalidationCheck object reflecting the (partitioned) targets.

    If no exceptions are thrown by work in the block, the build cache is updated for the targets.
    Note: the artifact cache is not updated, that must be done manually.
    """
    with self.invalidated_with_artifact_cache_check(targets,
                                                    only_buildfiles,
                                                    invalidate_dependents,
                                                    partition_size_hint) as check:
      yield check


  @contextmanager
  def invalidated_with_artifact_cache_check(self,
                                            targets,
                                            only_buildfiles=False,
                                            invalidate_dependents=False,
                                            partition_size_hint=sys.maxint):
    """Checks targets for invalidation, first checking the artifact cache.
    Subclasses call this to figure out what to work on.

    targets:               The targets to check for changes.
    only_buildfiles:       If True, then only the target's BUILD files are checked for changes, not
                           its sources.
    invalidate_dependents: If True then any targets depending on changed targets are invalidated.
    partition_size_hint:   Each VersionedTargetSet in the yielded list will represent targets
                           containing roughly this number of source files, if possible. Set to
                           sys.maxint for a single VersionedTargetSet. Set to 0 for one
                           VersionedTargetSet per target. It is up to the caller to do the right
                           thing with whatever partitioning it asks for.

    Yields a pair of (invalidation_check, cached_vts) where invalidation_check is an
    InvalidationCheck object reflecting the (partitioned) targets, and cached_vts is a list of
    VersionedTargets that were satisfied from the artifact cache.

    If no exceptions are thrown by work in the block, the build cache is updated for the targets.
    Note: the artifact cache is not updated, that must be done manually.
    """
    extra_data = []
    extra_data.append(self.invalidate_for())

    for f in self.invalidate_for_files():
      extra_data.append(hash_file(f))

    cache_manager = CacheManager(self._cache_key_generator,
                                 self._build_invalidator_dir,
                                 invalidate_dependents,
                                 extra_data,
                                 only_externaldeps=only_buildfiles)

    invalidation_check = cache_manager.check(targets, partition_size_hint)

    # See if we have entire partitions cached.
    if self._artifact_cache and self.context.options.read_from_artifact_cache:
      with self.context.new_workunit('cache'):
        all_cached_targets = []
        partitions_to_check = \
          [vt for vt in invalidation_check.all_vts_partitioned if not vt.valid]
        cached_partitions, uncached_partitions = self.check_artifact_cache(partitions_to_check)
        for vt in cached_partitions:
          for t in vt.targets:
            all_cached_targets.append(t)

        # See if we have any individual targets from the uncached partitions.
        vts_to_check = [vt for vt in itertools.chain.from_iterable(
          [x.versioned_targets for x in uncached_partitions]) if not vt.valid]
        cached_targets, uncached_targets = self.check_artifact_cache(vts_to_check)
        for vt in cached_targets:
          all_cached_targets.append(vt.target)

      if all_cached_targets:
        # Do some reporting.
        for t in all_cached_targets:
          self.context.run_tracker.artifact_cache_stats.add_hit('default', t)
        self._report_targets('Using cached artifacts for ', all_cached_targets, '.')

      # Now that we've checked the cache, re-partition whatever is still invalid.
      if uncached_targets:
        for vts in uncached_targets:
          self.context.run_tracker.artifact_cache_stats.add_miss('default', vts.target)
        self._report_targets('No cached artifacts for ',
                             [vt.target for vt in uncached_targets], '.')
      invalidation_check = \
        InvalidationCheck(invalidation_check.all_vts, uncached_targets, partition_size_hint)

    # Do some reporting.
    targets = []
    sources = []
    num_invalid_partitions = len(invalidation_check.invalid_vts_partitioned)
    for vt in invalidation_check.invalid_vts_partitioned:
      targets.extend(vt.targets)
      sources.extend(vt.cache_key.sources)
    if len(targets):
      msg_elements = ['Invalidated ',
                      items_to_report_element([t.address.reference() for t in targets], 'target')]
      if len(sources) > 0:
        msg_elements.append(' containing ')
        msg_elements.append(items_to_report_element(sources, 'source file'))
      if num_invalid_partitions > 1:
        msg_elements.append(' in %d target partitions' % num_invalid_partitions)
      msg_elements.append('.')
      self.context.log.info(*msg_elements)

    # Yield the result, and then mark the targets as up to date.
    yield invalidation_check
    if not self.dry_run:
      for vt in invalidation_check.invalid_vts:
        vt.update()  # In case the caller doesn't update.

  def check_artifact_cache(self, vts):
    """Checks the artifact cache for the specified VersionedTargetSets.

    Returns a list of the ones that were satisfied from the cache. These don't require building.
    """
    if not vts:
      return [], []

    cached_vts = []
    uncached_vts = OrderedSet(vts)

    with self.context.new_workunit('check'):
      pool = ThreadPool(processes=6)
      res = pool.map(lambda vt: self._artifact_cache.use_cached_files(vt.cache_key),
                     vts, chunksize=1)
      pool.close()
      pool.join()
      for vt, was_in_cache in zip(vts, res):
        if was_in_cache:
          cached_vts.append(vt)
          uncached_vts.discard(vt)
          vt.update()
    return cached_vts, list(uncached_vts)

  def update_artifact_cache(self, vts_artifactfiles_pairs):
    """Write to the artifact cache, if we're configured to.

    vts_artifactfiles_pairs - a list of pairs (vts, artifactfiles) where
      - vts is single VersionedTargetSet.
      - artifactfiles is a list of paths to artifacts for the VersionedTargetSet.
    """
    if self._artifact_cache and self.context.options.write_to_artifact_cache:
      with self.context.new_workunit('cache'):
        with self.context.new_workunit('update'):
          # Do some reporting.
          targets = set()
          for vts, artifactfiles in vts_artifactfiles_pairs:
            targets.update(vts.targets)
          self._report_targets('Caching artifacts for ', list(targets), '.')

          # Cache the artifacts.
          for vts, artifactfiles in vts_artifactfiles_pairs:
            if self.context.options.verify_artifact_cache:
              pass  # TODO: Verify that the artifact we just built is identical to the cached one.
            self._artifact_cache.insert(vts.cache_key, artifactfiles)

  def _report_targets(self, prefix, targets, suffix):
    self.context.log.info(
      prefix,
      items_to_report_element([t.address.reference() for t in targets], 'target'),
      suffix)

__all__ = (
  'TaskError',
  'Task'
)
