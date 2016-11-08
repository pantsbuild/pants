# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os

from pants.backend.jvm.ivy_utils import NO_RESOLVE_RUN_RESULT, IvyFetchStep, IvyResolveStep
from pants.backend.jvm.subsystems.jar_dependency_management import JarDependencyManagement
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.base.exceptions import TaskError
from pants.base.fingerprint_strategy import TaskIdentityFingerprintStrategy
from pants.invalidation.cache_manager import VersionedTargetSet
from pants.ivy.ivy_subsystem import IvySubsystem
from pants.task.task import TaskBase
from pants.util.memo import memoized_property


logger = logging.getLogger(__name__)


# TODO(nh): We could fingerprint just the ivy options and not the task options.
class IvyResolveFingerprintStrategy(TaskIdentityFingerprintStrategy):

  def __init__(self, task, confs):
    super(IvyResolveFingerprintStrategy, self).__init__(task)
    self._confs = sorted(confs or [])

  def compute_fingerprint(self, target):
    hash_elements_for_target = []

    if isinstance(target, JarLibrary):
      managed_jar_artifact_set = JarDependencyManagement.global_instance().for_target(target)
      if managed_jar_artifact_set:
        hash_elements_for_target.append(str(managed_jar_artifact_set.id))

      hash_elements_for_target.append(target.payload.fingerprint())
    elif isinstance(target, JvmTarget) and target.payload.excludes:
      hash_elements_for_target.append(target.payload.fingerprint(field_keys=('excludes',)))
    else:
      pass

    if not hash_elements_for_target:
      return None

    hasher = self._build_hasher(target)

    for conf in self._confs:
      hasher.update(conf)

    for element in hash_elements_for_target:
      hasher.update(element)

    return hasher.hexdigest()

  def __hash__(self):
    return hash((type(self), '-'.join(self._confs)))

  def __eq__(self, other):
    return type(self) == type(other) and self._confs == other._confs


class IvyTaskMixin(TaskBase):
  """A mixin for Tasks that execute resolves via Ivy.

  Must be mixed in to a task that registers a --jvm-options option (typically by
  extending NailgunTask).
  TODO: Get rid of this requirement by registering an --ivy-jvm-options below.

  :API: public
  """

  class Error(TaskError):
    """Indicates an error performing an ivy resolve."""

  class UnresolvedJarError(Error):
    """Indicates a jar dependency couldn't be mapped."""

  @classmethod
  def subsystem_dependencies(cls):
    return super(IvyTaskMixin, cls).subsystem_dependencies() + (IvySubsystem, JarDependencyManagement)

  @classmethod
  def register_options(cls, register):
    super(IvyTaskMixin, cls).register_options(register)
    # TODO: Register an --ivy-jvm-options here and use that, instead of the --jvm-options
    # registered by the task we mix into. That task may have intended those options for some
    # other JVM run than the Ivy one.
    register('--soft-excludes', type=bool, advanced=True, fingerprint=True,
             help='If a target depends on a jar that is excluded by another target '
                  'resolve this jar anyway')

  @classmethod
  def implementation_version(cls):
    return super(IvyTaskMixin, cls).implementation_version() + [('IvyTaskMixin', 2)]

  @memoized_property
  def ivy_cache_dir(self):
    """The path of the ivy cache dir used for resolves.

    :API: public

    :rtype: string
    """
    # TODO(John Sirois): Fixup the IvySubsystem to encapsulate its properties.
    return IvySubsystem.global_instance().get_options().cache_dir

  def resolve(self, executor, targets, classpath_products, confs=None, extra_args=None,
              invalidate_dependents=False):
    """Resolves external classpath products (typically jars) for the given targets.

    :API: public

    :param executor: A java executor to run ivy with.
    :type executor: :class:`pants.java.executor.Executor`
    :param targets: The targets to resolve jvm dependencies for.
    :type targets: :class:`collections.Iterable` of :class:`pants.build_graph.target.Target`
    :param classpath_products: The classpath products to populate with the results of the resolve.
    :type classpath_products: :class:`pants.backend.jvm.tasks.classpath_products.ClasspathProducts`
    :param confs: The ivy configurations to resolve; ('default',) by default.
    :type confs: :class:`collections.Iterable` of string
    :param extra_args: Any extra command line arguments to pass to ivy.
    :type extra_args: list of string
    :param bool invalidate_dependents: `True` to invalidate dependents of targets that needed to be
                                        resolved.
    :returns: The results of each of the resolves run by this call.
    :rtype: list of IvyResolveResult
    """
    confs = confs or ('default',)
    targets_by_sets = JarDependencyManagement.global_instance().targets_by_artifact_set(targets)
    results = []
    for artifact_set, target_subset in targets_by_sets.items():
      results.append(self._resolve_subset(executor,
                                                     target_subset,
                                                     classpath_products,
                                                     confs=confs,
                                                     extra_args=extra_args,
                                                     invalidate_dependents=invalidate_dependents,
                                                     pinned_artifacts=artifact_set))
    return results

  def ivy_classpath(self, targets, silent=True, workunit_name=None):
    """Create the classpath for the passed targets.

    :API: public

    :param targets: A collection of targets to resolve a classpath for.
    :type targets: collection.Iterable
    """
    result = self._ivy_resolve(targets, silent=silent, workunit_name=workunit_name)
    return result.resolved_artifact_paths

  def _resolve_subset(self, executor, targets, classpath_products, confs=None, extra_args=None,
              invalidate_dependents=False, pinned_artifacts=None):
    result = self._ivy_resolve(
      targets,
      executor=executor,
      workunit_name='ivy-resolve',
      confs=confs,
      extra_args=extra_args,
      invalidate_dependents=invalidate_dependents,
      pinned_artifacts=pinned_artifacts,
    )

    if not result.has_resolved_artifacts:
      # There was no resolve to do, so no 3rdparty deps to process below.
      return result

    # After running ivy, we update the classpath products with the excludes from the targets.
    # We also collect the resolved jar information for each target and update the classpath
    # appropriately.
    classpath_products.add_excludes_for_targets(targets)
    for conf in confs:
      for target, resolved_jars in result.resolved_jars_for_each_target(conf, targets):
        classpath_products.add_jars_for_targets([target], conf, resolved_jars)

    return result

  def _ivy_resolve(self,
                   targets,
                   executor=None,
                   silent=False,
                   workunit_name=None,
                   confs=None,
                   extra_args=None,
                   invalidate_dependents=False,
                   pinned_artifacts=None):
    """Resolves external dependencies for the given targets.

    If there are no targets suitable for jvm transitive dependency resolution, an empty result is
    returned.

    :param targets: The targets to resolve jvm dependencies for.
    :type targets: :class:`collections.Iterable` of :class:`pants.build_graph.target.Target`
    :param executor: A java executor to run ivy with.
    :type executor: :class:`pants.java.executor.Executor`

    :param confs: The ivy configurations to resolve; ('default',) by default.
    :type confs: :class:`collections.Iterable` of string
    :param extra_args: Any extra command line arguments to pass to ivy.
    :type extra_args: list of string
    :param bool invalidate_dependents: `True` to invalidate dependents of targets that needed to be
                                        resolved.
    :returns: The result of the resolve.
    :rtype: IvyResolveResult
    """
    # If there are no targets, we don't need to do a resolve.
    if not targets:
      return NO_RESOLVE_RUN_RESULT

    confs = confs or ('default',)

    fingerprint_strategy = IvyResolveFingerprintStrategy(self, confs)

    with self.invalidated(targets,
                          invalidate_dependents=invalidate_dependents,
                          silent=silent,
                          fingerprint_strategy=fingerprint_strategy) as invalidation_check:
      # In case all the targets were filtered out because they didn't participate in fingerprinting.
      if not invalidation_check.all_vts:
        return NO_RESOLVE_RUN_RESULT

      resolve_vts = VersionedTargetSet.from_versioned_targets(invalidation_check.all_vts)

      resolve_hash_name = resolve_vts.cache_key.hash
      global_ivy_workdir = os.path.join(self.context.options.for_global_scope().pants_workdir,
                                        'ivy')
      targets = resolve_vts.targets

      fetch = IvyFetchStep(confs,
                           resolve_hash_name,
                           pinned_artifacts,
                           self.get_options().soft_excludes,
                           self.ivy_cache_dir,
                           global_ivy_workdir)
      resolve = IvyResolveStep(confs,
                               resolve_hash_name,
                               pinned_artifacts,
                               self.get_options().soft_excludes,
                               self.ivy_cache_dir,
                               global_ivy_workdir)

      return self._perform_resolution(fetch, resolve, executor, extra_args, invalidation_check,
                                      resolve_vts, targets, workunit_name)

  def _perform_resolution(self, fetch, resolve, executor, extra_args, invalidation_check,
                          resolve_vts, targets, workunit_name):
    # Resolution loading code, fast paths followed by slow paths.
    #
    # Fast paths
    # 1. If last was successful fetch, load it.
    # 2. If last was successful resolve, load it.
    # Slow paths
    # 1. If the resolve file exists, do a fetch.
    # 2. Finally, if none of the above matches,
    #    - do a resolve.
    #    - cache the coordinates from the result.
    jvm_options = self.get_options().jvm_options
    workunit_factory = self.context.new_workunit

    if not invalidation_check.invalid_vts and fetch.required_load_files_exist():
      resolve_result = fetch.load(targets)
      if resolve_result.all_linked_artifacts_exist():
        logger.debug('Using previous fetch.')
        return resolve_result
    if not invalidation_check.invalid_vts and resolve.required_load_files_exist():
      result = resolve.load(targets)
      if result.all_linked_artifacts_exist():
        logger.debug('Using previous resolve.')
        return result

    if not invalidation_check.invalid_vts and fetch.required_exec_files_exist():
      logger.debug('Performing a fetch using ivy.')
      result = fetch.exec_and_load(executor, extra_args, targets, jvm_options, workunit_name,
                                   workunit_factory)
      if result.all_linked_artifacts_exist():
        return result
      else:
        logger.debug("Fetch failed, falling through to resolve.")

    logger.debug('Performing a resolve using ivy.')
    result = resolve.exec_and_load(executor, extra_args, targets, jvm_options, workunit_name,
                                   workunit_factory)
    if self.artifact_cache_writes_enabled():
      self.update_artifact_cache([(resolve_vts, [resolve.frozen_resolve_file])])
    return result
