# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import itertools
import os
import sys
from abc import abstractmethod
from contextlib import contextmanager

from twitter.common.collections.orderedset import OrderedSet

from pants.base.build_invalidator import BuildInvalidator, CacheKeyGenerator
from pants.base.cache_manager import InvalidationCacheManager, InvalidationCheck
from pants.base.exceptions import TaskError
from pants.base.fingerprint_strategy import TaskIdentityFingerprintStrategy
from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField
from pants.base.worker_pool import Work
from pants.cache.artifact_cache import UnreadableArtifact, call_insert, call_use_cached_files
from pants.cache.cache_setup import CacheSetup
from pants.option.optionable import Optionable
from pants.option.scope import ScopeInfo
from pants.reporting.reporting_utils import items_to_report_element
from pants.util.meta import AbstractClass


class TaskBase(Optionable, AbstractClass):
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
  # Tests may override this to provide a stable name despite the class name being a unique,
  # synthetic name.
  _stable_name = None

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
  def global_subsystems(cls):
    """The global subsystems this task uses.

    A tuple of subsystem types.
    """
    return tuple()

  @classmethod
  def task_subsystems(cls):
    """The private, per-task subsystems this task uses.

    A tuple of subsystem types.
    """
    return (CacheSetup,)

  @classmethod
  def product_types(cls):
    """The list of products this Task produces. Set the product type(s) for this
    task i.e. the product type(s) this task creates e.g ['classes'].

    By default, each task is considered as creating a unique product type(s).
    Subclasses that create products, should override this to specify their unique product type(s).
    """
    return []

  @classmethod
  def known_scope_infos(cls):
    """Yields ScopeInfo for all known scopes for this task, in no particular order."""
    # The task's own scope.
    yield ScopeInfo(cls.options_scope, ScopeInfo.TASK)
    # The scopes of any task-specific subsystems it uses.
    for subsystem in cls.task_subsystems():
      yield ScopeInfo(subsystem.subscope(cls.options_scope), ScopeInfo.TASK_SUBSYSTEM)

  @classmethod
  def supports_passthru_args(cls):
    """Subclasses may override to indicate that they can use passthru args."""
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

    :returns list: The new target roots to use or none to accept the CLI specified target roots.
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

    self._payload = None

  def get_options(self):
    """Returns the option values for this task's scope."""
    return self.context.options.for_scope(self.options_scope)

  def get_passthru_args(self):
    if not self.supports_passthru_args():
      raise TaskError('{0} Does not support passthru args.'.format(self.stable_name()))
    else:
      return self.context.options.passthru_args_for_scope(self.options_scope)

  @property
  def workdir(self):
    """A scratch-space for this task that will be deleted by `clean-all`.

    It's not guaranteed that the workdir exists, just that no other task has been given this
    workdir path to use.
    """
    return self._workdir

  @property
  def payload(self):
    if not self._payload:
      self._payload = Payload()
      registered = self.context.options.registration_args_iter_for_scope(self.options_scope)
      for (name, args, kwargs) in registered:
        if not kwargs.get('fingerprint', False):
          continue
        val = self.get_options()[name]
        self._payload.add_field(name, PrimitiveField(val))
      self._payload.freeze()

    return self._payload

  def artifact_cache_reads_enabled(self):
    return self._cache_factory.read_cache_available()

  def artifact_cache_writes_enabled(self):
    return self._cache_factory.write_cache_available()

  def invalidate_for_files(self):
    """Provides extra files that participate in invalidation.

    Subclasses can override and return a list of full paths to extra, non-source files that should
    be checked for changes when managing target invalidation. This is useful for tracking
    changes to pre-built build tools, e.g., the thrift compiler.
    """
    return []

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
                                    fingerprint_strategy=fingerprint_strategy)

  @property
  def cache_target_dirs(self):
    """Whether to cache files in VersionedTarget's results_dir after exiting an invalidated block.

    Subclasses may override this method to return True if they wish to use this style
    of "automated" caching, where each VersionedTarget is given an associated results directory,
    which will automatically be uploaded to the cache. Tasks should place the output files
    for each VersionedTarget in said results directory. It is highly suggested to follow this
    schema for caching, rather than manually making updates to the artifact cache.
    """
    return False

  @contextmanager
  def invalidated(self,
                  targets,
                  invalidate_dependents=False,
                  partition_size_hint=sys.maxint,
                  silent=False,
                  locally_changed_targets=None,
                  fingerprint_strategy=None,
                  topological_order=False):
    """Checks targets for invalidation, first checking the artifact cache.

    Subclasses call this to figure out what to work on.

    :param targets:               The targets to check for changes.
    :param invalidate_dependents: If True then any targets depending on changed targets are invalidated.
    :param partition_size_hint:   Each VersionedTargetSet in the yielded list will represent targets
                                  containing roughly this number of source files, if possible. Set to
                                  sys.maxint for a single VersionedTargetSet. Set to 0 for one
                                  VersionedTargetSet per target. It is up to the caller to do the right
                                  thing with whatever partitioning it asks for.
    :param locally_changed_targets: Targets that we've edited locally. If specified, and there aren't too
                                  many of them, we keep these in separate partitions from other targets,
                                  as these are more likely to have build errors, and so to be rebuilt over
                                  and over, and partitioning them separately is a performance win.
    :param fingerprint_strategy:   A FingerprintStrategy instance, which can do per task, finer grained
                                  fingerprinting of a given Target.

    If no exceptions are thrown by work in the block, the build cache is updated for the targets.
    Note: the artifact cache is not updated. That must be done manually.

    :returns: Yields an InvalidationCheck object reflecting the (partitioned) targets.
    :rtype: InvalidationCheck
    """

    # TODO(benjy): Compute locally_changed_targets here instead of passing it in? We currently pass
    # it in because JvmCompile already has the source->target mapping for other reasons, and also
    # to selectively enable this feature.
    fingerprint_strategy = fingerprint_strategy or TaskIdentityFingerprintStrategy(self)
    cache_manager = self.create_cache_manager(invalidate_dependents,
                                              fingerprint_strategy=fingerprint_strategy)

    # We separate locally-modified targets from others by coloring them differently.
    # This can be a performance win, because these targets are more likely to be iterated
    # over, and this preserves "chunk stability" for them.
    colors = {}

    # But we only do so if there aren't too many, or this optimization will backfire.
    locally_changed_target_limit = 10

    if locally_changed_targets and len(locally_changed_targets) < locally_changed_target_limit:
      for t in targets:
        if t in locally_changed_targets:
          colors[t] = 'locally_changed'
        else:
          colors[t] = 'not_locally_changed'
    invalidation_check = cache_manager.check(targets, partition_size_hint, colors, topological_order=topological_order)

    if invalidation_check.invalid_vts and self.artifact_cache_reads_enabled():
      with self.context.new_workunit('cache'):
        cached_vts, uncached_vts = \
          self.check_artifact_cache(self.check_artifact_cache_for(invalidation_check))
      if cached_vts:
        cached_targets = [vt.target for vt in cached_vts]
        for t in cached_targets:
          self.context.run_tracker.artifact_cache_stats.add_hit('default', t)
        if not silent:
          self._report_targets('Using cached artifacts for ', cached_targets, '.')
      if uncached_vts:
        uncached_targets = [vt.target for vt in uncached_vts]
        for t in uncached_targets:
          self.context.run_tracker.artifact_cache_stats.add_miss('default', t)
        if not silent:
          self._report_targets('No cached artifacts for ', uncached_targets, '.')
      # Now that we've checked the cache, re-partition whatever is still invalid.
      invalidation_check = \
        InvalidationCheck(invalidation_check.all_vts, uncached_vts, partition_size_hint, colors)

    if self.cache_target_dirs:
      for vt in invalidation_check.all_vts:
        vt.create_results_dir(os.path.join(self.workdir, vt.cache_key.hash))

    if not silent:
      targets = []
      num_invalid_partitions = len(invalidation_check.invalid_vts_partitioned)
      for vt in invalidation_check.invalid_vts_partitioned:
        targets.extend(vt.targets)

      if len(targets):
        msg_elements = ['Invalidated ',
                        items_to_report_element([t.address.reference() for t in targets], 'target')]
        if num_invalid_partitions > 1:
          msg_elements.append(' in {} target partitions'.format(num_invalid_partitions))
        msg_elements.append('.')
        self.context.log.info(*msg_elements)

    # Yield the result, and then mark the targets as up to date.
    yield invalidation_check

    for vt in invalidation_check.invalid_vts:
      vt.update()  # In case the caller doesn't update.

    write_to_cache = (self.cache_target_dirs
                      and self.artifact_cache_writes_enabled()
                      and invalidation_check.invalid_vts)
    if write_to_cache:
      def result_files(vt):
        return [os.path.join(vt.results_dir, f) for f in os.listdir(vt.results_dir)]
      pairs = [(vt, result_files(vt)) for vt in invalidation_check.invalid_vts]
      self.update_artifact_cache(pairs)

  def check_artifact_cache_for(self, invalidation_check):
    """Decides which VTS to check the artifact cache for.

    By default we check for each invalid target. Can be overridden, e.g., to
    instead check only for a single artifact for the entire target set.
    """
    return invalidation_check.invalid_vts

  def check_artifact_cache(self, vts):
    """Checks the artifact cache for the specified list of VersionedTargetSets.

    Returns a pair (cached, uncached) of VersionedTargets that were
    satisfied/unsatisfied from the cache.
    """
    return self.do_check_artifact_cache(vts)

  def do_check_artifact_cache(self, vts, post_process_cached_vts=None):
    """Checks the artifact cache for the specified list of VersionedTargetSets.

    Returns a pair (cached, uncached) of VersionedTargets that were
    satisfied/unsatisfied from the cache.
    """
    if not vts:
      return [], []

    cached_vts = []
    uncached_vts = OrderedSet(vts)

    read_cache = self._cache_factory.get_read_cache()
    items = [(read_cache, vt.cache_key) for vt in vts]

    res = self.context.subproc_map(call_use_cached_files, items)

    for vt, was_in_cache in zip(vts, res):
      if was_in_cache:
        cached_vts.append(vt)
        uncached_vts.discard(vt)
      elif isinstance(was_in_cache, UnreadableArtifact):
        self._cache_key_errors.update(was_in_cache.key)

    # Note that while the input vts may represent multiple targets (for tasks that overrride
    # check_artifact_cache_for), the ones we return must represent single targets.
    def flatten(vts):
      return list(itertools.chain.from_iterable([vt.versioned_targets for vt in vts]))
    all_cached_vts, all_uncached_vts = flatten(cached_vts), flatten(uncached_vts)
    if post_process_cached_vts:
      post_process_cached_vts(all_cached_vts)
    for vt in all_cached_vts:
      vt.update()
    return all_cached_vts, all_uncached_vts

  def update_artifact_cache(self, vts_artifactfiles_pairs):
    """Write to the artifact cache, if we're configured to.

    vts_artifactfiles_pairs - a list of pairs (vts, artifactfiles) where
      - vts is single VersionedTargetSet.
      - artifactfiles is a list of absolute paths to artifacts for the VersionedTargetSet.
    """
    update_artifact_cache_work = self.get_update_artifact_cache_work(vts_artifactfiles_pairs)
    if update_artifact_cache_work:
      self.context.submit_background_work_chain([update_artifact_cache_work],
                                                parent_workunit_name='cache')

  def get_update_artifact_cache_work(self, vts_artifactfiles_pairs):
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
      self._report_targets('Caching artifacts for ', list(targets), '.')

      always_overwrite = self._cache_factory.overwrite()

      # Cache the artifacts.
      args_tuples = []
      for vts, artifactfiles in vts_artifactfiles_pairs:
        overwrite = always_overwrite or vts.cache_key in self._cache_key_errors
        args_tuples.append((cache, vts.cache_key, artifactfiles, overwrite))

      return Work(lambda x: self.context.subproc_map(call_insert, x), [(args_tuples,)], 'insert')
    else:
      return None

  def _report_targets(self, prefix, targets, suffix):
    self.context.log.info(
      prefix,
      items_to_report_element([t.address.reference() for t in targets], 'target'),
      suffix)

  def require_single_root_target(self):
    """If a single target was specified on the cmd line, returns that target.

    Otherwise throws TaskError.
    """
    target_roots = self.context.target_roots
    if len(target_roots) == 0:
      raise TaskError('No target specified.')
    elif len(target_roots) > 1:
      raise TaskError('Multiple targets specified: {}'
                      .format(', '.join([repr(t) for t in target_roots])))
    return target_roots[0]

  def require_homogeneous_targets(self, accept_predicate, reject_predicate):
    """Ensures that there is no ambiguity in the context according to the given predicates.

    If any targets in the context satisfy the accept_predicate, and no targets satisfy the
    reject_predicate, returns the accepted targets.

    If no targets satisfy the accept_predicate, returns None.

    Otherwise throws TaskError.
    """
    if len(self.context.target_roots) == 0:
      raise TaskError('No target specified.')

    accepted = self.context.targets(accept_predicate)
    rejected = self.context.targets(reject_predicate)
    if len(accepted) == 0:
      # no targets were accepted, regardless of rejects
      return None
    elif len(rejected) == 0:
      # we have at least one accepted target, and no rejected targets
      return accepted
    else:
      # both accepted and rejected targets
      # TODO: once https://github.com/pantsbuild/pants/issues/425 lands, we should add
      # language-specific flags that would resolve the ambiguity here
      raise TaskError('Mutually incompatible targets specified: {} vs {} (and {} others)'
                      .format(accepted[0], rejected[0], len(accepted) + len(rejected) - 2))


class Task(TaskBase):
  """An executable task.

  Tasks form the atoms of work done by pants and when executed generally produce artifacts as a
  side effect whether these be files on disk (for example compilation outputs) or characters output
  to the terminal (for example dependency graph metadata).
  """

  @abstractmethod
  def execute(self):
    """Executes this task."""


class QuietTaskMixin(object):
  """A mixin to signal that pants shouldn't print verbose progress information for this task."""
  pass
