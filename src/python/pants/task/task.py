# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
from abc import abstractmethod
from contextlib import contextmanager
from hashlib import sha1
from itertools import repeat

from pants.base.exceptions import TaskError
from pants.base.fingerprint_strategy import TaskIdentityFingerprintStrategy
from pants.base.worker_pool import Work
from pants.cache.artifact_cache import UnreadableArtifact, call_insert, call_use_cached_files
from pants.cache.cache_setup import CacheSetup
from pants.invalidation.build_invalidator import BuildInvalidator, CacheKeyGenerator
from pants.invalidation.cache_manager import InvalidationCacheManager, InvalidationCheck
from pants.option.optionable import Optionable
from pants.option.options_fingerprinter import OptionsFingerprinter
from pants.option.scope import ScopeInfo
from pants.reporting.reporting_utils import items_to_report_element
from pants.subsystem.subsystem_client_mixin import SubsystemClientMixin
from pants.util.dirutil import safe_rm_oldest_items_in_dir
from pants.util.memo import memoized_method, memoized_property
from pants.util.meta import AbstractClass


logger = logging.getLogger(__name__)


class TaskBase(SubsystemClientMixin, Optionable, AbstractClass):
  """Defines a lifecycle that prepares a task for execution and provides the base machinery
  needed to execute it.

  Provides the base lifecycle methods that allow a task to interact with the command line, other
  tasks and the user.  The lifecycle is linear and run via the following sequence:
  1. register_options - declare options configurable via cmd-line flag or config file.
  2. product_types - declare the product types your task is capable of producing.
  3. alternate_target_roots - propose a different set of target roots to use than those specified
                              via the CLI for the active pants run.
  4. prepare - request any products needed from other tasks.
  5. __init__ - distill configuration into the information needed to execute.

  Provides access to the current run context for scoping work.

  Also provides the basic facilities for doing work efficiently including providing a work directory
  for scratch space on disk, an invalidator for checking which targets need work done on, and an
  artifact cache for re-using previously cached work.

  #TODO(John Sirois):  Lifecycle is currently split between TaskBase and Task and lifecycle
  (interface) and helpers (utility) are currently conflated.  Tease these apart and narrow the scope
  of the helpers.  Ideally console tasks don't inherit a workdir, invalidator or build cache for
  example.
  """
  options_scope_category = ScopeInfo.TASK

  # We set this explicitly on the synthetic subclass, so that it shares a stable name with
  # its superclass, which is not necessary for regular use, but can be convenient in tests.
  _stable_name = None

  @classmethod
  def implementation_version(cls):
    """
    :API: public
    """
    return [('TaskBase', 2)]

  @classmethod
  @memoized_method
  def implementation_version_str(cls):
    return '.'.join(['_'.join(map(str, x)) for x in cls.implementation_version()])

  @classmethod
  def stable_name(cls):
    """The stable name of this task type.

    We synthesize subclasses of the task types at runtime, and these synthesized subclasses
    may have random names (e.g., in tests), so this gives us a stable name to use across runs,
    e.g., in artifact cache references.
    """
    return cls._stable_name or cls._compute_stable_name()

  @classmethod
  def _compute_stable_name(cls):
    return '{}_{}'.format(cls.__module__, cls.__name__).replace('.', '_')

  @classmethod
  def subsystem_dependencies(cls):
    return super(TaskBase, cls).subsystem_dependencies() + (CacheSetup.scoped(cls),)

  @classmethod
  def product_types(cls):
    """The list of products this Task produces. Set the product type(s) for this
    task i.e. the product type(s) this task creates e.g ['classes'].

    By default, each task is considered as creating a unique product type(s).
    Subclasses that create products, should override this to specify their unique product type(s).

    :API: public
    """
    return []

  @classmethod
  def known_scope_infos(cls):
    """Yields ScopeInfo for all known scopes for this task, in no particular order."""
    # The task's own scope.
    yield cls.get_scope_info()
    # The scopes of any task-specific subsystems it uses.
    for dep in cls.subsystem_dependencies_iter():
      if not dep.is_global():
        yield dep.subsystem_cls.get_scope_info(subscope=dep.scope)

  @classmethod
  def supports_passthru_args(cls):
    """Subclasses may override to indicate that they can use passthru args.

    :API: public
    """
    return False

  @classmethod
  def _scoped_options(cls, options):
    return options[cls.options_scope]

  @classmethod
  def _alternate_target_roots(cls, options, address_mapper, build_graph):
    # Subclasses should not generally need to override this method.
    # TODO(John Sirois): Kill when killing GroupTask as part of RoundEngine parallelization.
    return cls.alternate_target_roots(cls._scoped_options(options), address_mapper, build_graph)

  @classmethod
  def alternate_target_roots(cls, options, address_mapper, build_graph):
    """Allows a Task to propose alternate target roots from those specified on the CLI.

    At most 1 unique proposal is allowed amongst all tasks involved in the run.  If more than 1
    unique list of target roots is proposed an error is raised during task scheduling.

    :API: public

    :returns list: The new target roots to use or None to accept the CLI specified target roots.
    """

  @classmethod
  def _prepare(cls, options, round_manager):
    # Subclasses should not generally need to override this method.
    # TODO(John Sirois): Kill when killing GroupTask as part of RoundEngine parallelization.
    return cls.prepare(cls._scoped_options(options), round_manager)

  @classmethod
  def prepare(cls, options, round_manager):
    """Prepares a task for execution.

    Called before execution and prior to any tasks that may be (indirectly) depended upon.

    Typically a task that requires products from other goals would register interest in those
    products here and then retrieve the requested product mappings when executed.

    :API: public
    """

  def __init__(self, context, workdir):
    """Subclass __init__ methods, if defined, *must* follow this idiom:

    class MyTask(Task):
      def __init__(self, *args, **kwargs):
        super(MyTask, self).__init__(*args, **kwargs)
        ...

    This allows us to change Task.__init__()'s arguments without
    changing every subclass. If the subclass does not need its own
    initialization, this method can (and should) be omitted entirely.

    :API: public
    """
    super(TaskBase, self).__init__()
    self.context = context
    self._workdir = workdir
    # TODO: It would be nice to use self.get_options().cache_key_gen_version here, because then
    # we could have a separate value for each scope if we really wanted to. However we can't
    # access per-task options in Task.__init__ because GroupTask.__init__ calls it with the
    # group task's scope, which isn't currently in the known scopes we generate options for.
    self._cache_key_generator = CacheKeyGenerator(
      self.context.options.for_global_scope().cache_key_gen_version)

    self._cache_key_errors = set()

    self._build_invalidator_dir = os.path.join(
      self.context.options.for_global_scope().pants_workdir,
      'build_invalidator',
      self.stable_name())

    self._cache_factory = CacheSetup.create_cache_factory_for_task(self)

    self._options_fingerprinter = OptionsFingerprinter(self.context.build_graph)

  def get_options(self):
    """Returns the option values for this task's scope.

    :API: public
    """
    return self.context.options.for_scope(self.options_scope)

  def get_passthru_args(self):
    """
    :API: public
    """
    if not self.supports_passthru_args():
      raise TaskError('{0} Does not support passthru args.'.format(self.stable_name()))
    else:
      return self.context.options.passthru_args_for_scope(self.options_scope)

  @property
  def workdir(self):
    """A scratch-space for this task that will be deleted by `clean-all`.

    It's not guaranteed that the workdir exists, just that no other task has been given this
    workdir path to use.

    :API: public
    """
    return self._workdir

  def _options_fingerprint(self, scope):
    pairs = self.context.options.get_fingerprintable_for_scope(scope)
    hasher = sha1()
    for (option_type, option_val) in pairs:
      fp = self._options_fingerprinter.fingerprint(option_type, option_val)
      if fp is not None:
        hasher.update(fp)
    return hasher.hexdigest()

  @memoized_property
  def fingerprint(self):
    """Returns a fingerprint for the identity of the task.

    A task fingerprint is composed of the options the task is currently running under.
    Useful for invalidating unchanging targets being executed beneath changing task
    options that affect outputted artifacts.

    A task's fingerprint is only valid afer the task has been fully initialized.
    """
    hasher = sha1()
    hasher.update(self._options_fingerprint(self.options_scope))
    hasher.update(self.implementation_version_str())
    # TODO: this is not recursive, but should be: see #2739
    for dep in self.subsystem_dependencies_iter():
      hasher.update(self._options_fingerprint(dep.options_scope()))
    return str(hasher.hexdigest())

  def artifact_cache_reads_enabled(self):
    return self._cache_factory.read_cache_available()

  def artifact_cache_writes_enabled(self):
    return self._cache_factory.write_cache_available()

  def invalidate(self):
    """Invalidates all targets for this task."""
    BuildInvalidator(self._build_invalidator_dir).force_invalidate_all()

  def create_cache_manager(self, invalidate_dependents, fingerprint_strategy=None):
    """Creates a cache manager that can be used to invalidate targets on behalf of this task.

    Use this if you need to check for invalid targets but can't use the contextmanager created by
    invalidated(), e.g., because you don't want to mark the targets as valid when done.

    invalidate_dependents:   If True then any targets depending on changed targets are invalidated.
    fingerprint_strategy:    A FingerprintStrategy instance, which can do per task, finer grained
                             fingerprinting of a given Target.
    """

    return InvalidationCacheManager(self._cache_key_generator,
                                    self._build_invalidator_dir,
                                    invalidate_dependents,
                                    fingerprint_strategy=fingerprint_strategy,
                                    invalidation_report=self.context.invalidation_report,
                                    task_name=type(self).__name__,
                                    task_version=self.implementation_version_str(),
                                    artifact_write_callback=self.maybe_write_artifact)

  @property
  def create_target_dirs(self):
    """Whether to create a results_dir per VersionedTarget in the workdir of the Task.

    This defaults to the value of `self.cache_target_dirs` (as caching them requires
    creating them), but may be overridden independently to create the dirs without caching
    them.

    :API: public
    """
    return self.cache_target_dirs or False

  @property
  def cache_target_dirs(self):
    """Whether to cache files in VersionedTarget's results_dir after exiting an invalidated block.

    Subclasses may override this method to return True if they wish to use this style
    of "automated" caching, where each VersionedTarget is given an associated results directory,
    which will automatically be uploaded to the cache. Tasks should place the output files
    for each VersionedTarget in said results directory. It is highly suggested to follow this
    schema for caching, rather than manually making updates to the artifact cache.

    :API: public
    """
    return False

  @property
  def incremental(self):
    """Whether this Task implements incremental building of individual targets.

    Incremental tasks with `cache_target_dirs` set will have the results_dir of the previous build
    for a target cloned into the results_dir for the current build (where possible). This
    copy-on-write behaviour allows for immutability of the results_dir once a target has been
    marked valid.

    :API: public
    """
    return False

  @property
  def cache_incremental(self):
    """For incremental tasks, indicates whether the results of incremental builds should be cached.

    Deterministic per-target incremental compilation is a relatively difficult thing to implement,
    so this property provides an escape hatch to avoid caching things in that riskier case.

    :API: public
    """
    return False

  @contextmanager
  def invalidated(self,
                  targets,
                  invalidate_dependents=False,
                  silent=False,
                  fingerprint_strategy=None,
                  topological_order=False):
    """Checks targets for invalidation, first checking the artifact cache.

    Subclasses call this to figure out what to work on.

    :API: public

    :param targets:               The targets to check for changes.
    :param invalidate_dependents: If True then any targets depending on changed targets are invalidated.
    :param fingerprint_strategy:   A FingerprintStrategy instance, which can do per task, finer grained
                                  fingerprinting of a given Target.

    If no exceptions are thrown by work in the block, the build cache is updated for the targets.
    Note: the artifact cache is not updated. That must be done manually.

    :returns: Yields an InvalidationCheck object reflecting the targets.
    :rtype: InvalidationCheck
    """

    fingerprint_strategy = fingerprint_strategy or TaskIdentityFingerprintStrategy(self)
    cache_manager = self.create_cache_manager(invalidate_dependents,
                                              fingerprint_strategy=fingerprint_strategy)

    invalidation_check = cache_manager.check(targets, topological_order=topological_order)

    self._maybe_create_results_dirs(invalidation_check.all_vts)

    if invalidation_check.invalid_vts and self.artifact_cache_reads_enabled():
      with self.context.new_workunit('cache'):
        cached_vts, uncached_vts, uncached_causes = \
          self.check_artifact_cache(self.check_artifact_cache_for(invalidation_check))
      if cached_vts:
        cached_targets = [vt.target for vt in cached_vts]
        self.context.run_tracker.artifact_cache_stats.add_hits(cache_manager.task_name,
                                                               cached_targets)
        if not silent:
          self._report_targets('Using cached artifacts for ', cached_targets, '.')
      if uncached_vts:
        uncached_targets = [vt.target for vt in uncached_vts]
        self.context.run_tracker.artifact_cache_stats.add_misses(cache_manager.task_name,
                                                                 uncached_targets,
                                                                 uncached_causes)
        if not silent:
          self._report_targets('No cached artifacts for ', uncached_targets, '.')
      # Now that we've checked the cache, re-partition whatever is still invalid.
      invalidation_check = \
        InvalidationCheck(invalidation_check.all_vts, uncached_vts)

    if not silent:
      targets = []
      for vt in invalidation_check.invalid_vts:
        targets.extend(vt.targets)

      if len(targets):
        msg_elements = ['Invalidated ',
                        items_to_report_element([t.address.reference() for t in targets], 'target')]
        msg_elements.append('.')
        self.context.log.info(*msg_elements)

    invalidation_report = self.context.invalidation_report
    if invalidation_report:
      for vts in invalidation_check.all_vts:
        invalidation_report.add_vts(cache_manager, vts.targets, vts.cache_key, vts.valid,
                                    phase='pre-check')

    # Yield the result, and then mark the targets as up to date.
    yield invalidation_check

    if invalidation_report:
      for vts in invalidation_check.all_vts:
        invalidation_report.add_vts(cache_manager, vts.targets, vts.cache_key, vts.valid,
                                    phase='post-check')

    for vt in invalidation_check.invalid_vts:
      vt.update()

    # Background work to clean up previous builds.
    if self.context.options.for_global_scope().workdir_max_build_entries is not None:
      self._launch_background_workdir_cleanup(invalidation_check.all_vts)

  def maybe_write_artifact(self, vt):
    if self._should_cache_target_dir(vt):
      self.update_artifact_cache([(vt, [vt.current_results_dir])])

  def _launch_background_workdir_cleanup(self, vts):
    workdir_build_cleanup_job = Work(self._cleanup_workdir_stale_builds, [(vts,)], 'workdir_build_cleanup')
    self.context.submit_background_work_chain([workdir_build_cleanup_job])

  def _cleanup_workdir_stale_builds(self, vts):
    # workdir_max_build_entries has been assured of not None before invoking this method.
    max_entries_per_target = max(2, self.context.options.for_global_scope().workdir_max_build_entries)
    for vt in vts:
      live_dirs = list(vt.live_dirs())
      if not live_dirs:
        continue
      root_dir = os.path.dirname(vt.results_dir)
      safe_rm_oldest_items_in_dir(root_dir, max_entries_per_target, excludes=live_dirs)

  def _should_cache_target_dir(self, vt):
    """Return true if the given vt should be written to a cache (if configured)."""
    return (
      self.cache_target_dirs and
      not vt.target.has_label('no_cache') and
      (not vt.is_incremental or self.cache_incremental) and
      self.artifact_cache_writes_enabled()
    )

  def _maybe_create_results_dirs(self, vts):
    """If `cache_target_dirs`, create results_dirs for the given versioned targets."""
    if self.create_target_dirs:
      for vt in vts:
        vt.create_results_dir(self.workdir, allow_incremental=self.incremental)

  def check_artifact_cache_for(self, invalidation_check):
    """Decides which VTS to check the artifact cache for.

    By default we check for each invalid target. Can be overridden, e.g., to
    instead check only for a single artifact for the entire target set.
    """
    return invalidation_check.invalid_vts

  def check_artifact_cache(self, vts):
    """Checks the artifact cache for the specified list of VersionedTargetSets.

    Returns a tuple (cached, uncached, uncached_causes) of VersionedTargets that were
    satisfied/unsatisfied from the cache. Uncached VTS are also attached with their
    causes for the miss: `False` indicates a legit miss while `UnreadableArtifact`
    is due to either local or remote cache failures.
    """
    return self.do_check_artifact_cache(vts)

  def do_check_artifact_cache(self, vts, post_process_cached_vts=None):
    """Checks the artifact cache for the specified list of VersionedTargetSets.

    Returns a pair (cached, uncached) of VersionedTargets that were
    satisfied/unsatisfied from the cache.
    """
    if not vts:
      return [], [], []

    read_cache = self._cache_factory.get_read_cache()
    items = [(read_cache, vt.cache_key, vt.current_results_dir if self.cache_target_dirs else None)
             for vt in vts]

    res = self.context.subproc_map(call_use_cached_files, items)

    self._maybe_create_results_dirs(vts)

    cached_vts = []
    uncached_vts = []
    uncached_causes = []

    # Note that while the input vts may represent multiple targets (for tasks that overrride
    # check_artifact_cache_for), the ones we return must represent single targets.
    # Once flattened, cached/uncached vts are in separate lists. Each uncached vts is paired
    # with why it is missed for stat reporting purpose.
    for vt, was_in_cache in zip(vts, res):
      if was_in_cache:
        cached_vts.extend(vt.versioned_targets)
      else:
        uncached_vts.extend(vt.versioned_targets)
        uncached_causes.extend(repeat(was_in_cache, len(vt.versioned_targets)))
        if isinstance(was_in_cache, UnreadableArtifact):
          self._cache_key_errors.update(was_in_cache.key)

    if post_process_cached_vts:
      post_process_cached_vts(cached_vts)
    for vt in cached_vts:
      vt.update()
    return cached_vts, uncached_vts, uncached_causes

  def update_artifact_cache(self, vts_artifactfiles_pairs):
    """Write to the artifact cache, if we're configured to.

    vts_artifactfiles_pairs - a list of pairs (vts, artifactfiles) where
      - vts is single VersionedTargetSet.
      - artifactfiles is a list of absolute paths to artifacts for the VersionedTargetSet.
    """
    update_artifact_cache_work = self._get_update_artifact_cache_work(vts_artifactfiles_pairs)
    if update_artifact_cache_work:
      self.context.submit_background_work_chain([update_artifact_cache_work],
                                                parent_workunit_name='cache')

  def _get_update_artifact_cache_work(self, vts_artifactfiles_pairs):
    """Create a Work instance to update an artifact cache, if we're configured to.

    vts_artifactfiles_pairs - a list of pairs (vts, artifactfiles) where
      - vts is single VersionedTargetSet.
      - artifactfiles is a list of paths to artifacts for the VersionedTargetSet.
    """
    cache = self._cache_factory.get_write_cache()
    if cache:
      if len(vts_artifactfiles_pairs) == 0:
        return None
        # Do some reporting.
      targets = set()
      for vts, _ in vts_artifactfiles_pairs:
        targets.update(vts.targets)

      self._report_targets(
        'Caching artifacts for ',
        list(targets),
        '.',
        logger=self.context.log.debug,
      )

      always_overwrite = self._cache_factory.overwrite()

      # Cache the artifacts.
      args_tuples = []
      for vts, artifactfiles in vts_artifactfiles_pairs:
        overwrite = always_overwrite or vts.cache_key in self._cache_key_errors
        args_tuples.append((cache, vts.cache_key, artifactfiles, overwrite))

      return Work(lambda x: self.context.subproc_map(call_insert, x), [(args_tuples,)], 'insert')
    else:
      return None

  def _report_targets(self, prefix, targets, suffix, logger=None):
    logger = logger or self.context.log.info
    logger(
      prefix,
      items_to_report_element([t.address.reference() for t in targets], 'target'),
      suffix,
    )

  def require_single_root_target(self):
    """If a single target was specified on the cmd line, returns that target.

    Otherwise throws TaskError.

    :API: public
    """
    target_roots = self.context.target_roots
    if len(target_roots) == 0:
      raise TaskError('No target specified.')
    elif len(target_roots) > 1:
      raise TaskError('Multiple targets specified: {}'
                      .format(', '.join([repr(t) for t in target_roots])))
    return target_roots[0]

  def determine_target_roots(self, goal_name, predicate=None):
    """Helper for tasks that scan for default target roots.

    :param string goal_name: The goal name to use for any warning emissions.
    :param callable predicate: The predicate to pass to `context.scan().targets(predicate=X)`.
    """
    if not self.context.target_roots and not self.get_options().enable_v2_engine:
      logger.warn('The behavior of `./pants {0}` (no explicit targets) will soon become a no-op. '
                  'To remove this warning, please specify one or more explicit target specs (e.g. '
                  '`./pants {0} ::`).'.format(goal_name))
      # For the v1 path, continue the behavior of e.g. `./pants list` implies `./pants list ::`.
      return self.context.scan().targets(predicate=predicate)

    # For the v2 path, e.g. `./pants list` is a functional no-op. This matches the v2 mode behavior
    # of e.g. `./pants --changed-parent=HEAD list` (w/ no changes) returning an empty result.
    return self.context.target_roots


class Task(TaskBase):
  """An executable task.

  Tasks form the atoms of work done by pants and when executed generally produce artifacts as a
  side effect whether these be files on disk (for example compilation outputs) or characters output
  to the terminal (for example dependency graph metadata).

  :API: public
  """

  def __init__(self, context, workdir):
    """
    Add pass-thru Task Constructor for public API visibility.

    :API: public
    """
    super(Task, self).__init__(context, workdir)

  @abstractmethod
  def execute(self):
    """Executes this task.

    :API: public
    """


class QuietTaskMixin(object):
  """A mixin to signal that pants shouldn't print verbose progress information for this task."""
  pass
