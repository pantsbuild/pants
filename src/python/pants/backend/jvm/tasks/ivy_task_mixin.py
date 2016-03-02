# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
import threading
from hashlib import sha1

from pants.backend.jvm.ivy_utils import IvyResolveRequest, IvyUtils
from pants.backend.jvm.jar_dependency_utils import ResolvedJar
from pants.backend.jvm.subsystems.jar_dependency_management import JarDependencyManagement
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.base.exceptions import TaskError
from pants.base.fingerprint_strategy import FingerprintStrategy
from pants.invalidation.cache_manager import VersionedTargetSet
from pants.ivy.bootstrapper import Bootstrapper
from pants.ivy.ivy_subsystem import IvySubsystem
from pants.task.task import TaskBase
from pants.util.fileutil import atomic_copy
from pants.util.memo import memoized_property


logger = logging.getLogger(__name__)


class IvyResolveFingerprintStrategy(FingerprintStrategy):

  def __init__(self, confs):
    super(IvyResolveFingerprintStrategy, self).__init__()
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

    hasher = sha1()
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

  NB: Ivy reports are not relocatable in a cache, and a report must be present in order to
  parse the graph structure of dependencies. Therefore, this mixin explicitly disables the
  cache for its invalidation checks via the `use_cache=False` parameter. Tasks that extend
  the mixin may safely enable task-level caching settings.

  :API: public
  """

  class Error(TaskError):
    """Indicates an error performing an ivy resolve."""

  class UnresolvedJarError(Error):
    """Indicates a jar dependency couldn't be mapped."""

  @classmethod
  def global_subsystems(cls):
    return super(IvyTaskMixin, cls).global_subsystems() + (IvySubsystem, JarDependencyManagement)

  @classmethod
  def register_options(cls, register):
    super(IvyTaskMixin, cls).register_options(register)
    register('--jvm-options', action='append', metavar='<option>...',
             help='Run Ivy with these extra jvm options.')
    register('--soft-excludes', action='store_true', default=False, advanced=True,
             help='If a target depends on a jar that is excluded by another target '
                  'resolve this jar anyway')

  # Protect writes to the global map of jar path -> symlinks to that jar.
  symlink_map_lock = threading.Lock()

  @classmethod
  def implementation_version(cls):
    return super(IvyTaskMixin, cls).implementation_version() + [('IvyTaskMixin', 1)]

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
    :returns: The ids of the reports associated with this resolve.
    :rtype: list of string
    """
    confs = confs or ('default',)
    targets_by_sets = JarDependencyManagement.global_instance().targets_by_artifact_set(targets)
    resolve_hash_names = []
    for artifact_set, target_subset in targets_by_sets.items():
      resolve_hash_names.append(self._resolve_subset(executor,
                                                     target_subset,
                                                     classpath_products,
                                                     confs=confs,
                                                     extra_args=extra_args,
                                                     invalidate_dependents=invalidate_dependents,
                                                     pinned_artifacts=artifact_set))
    return resolve_hash_names

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
      return

    # After running ivy, we update the classpath products with the excludes from the targets.
    # We also collect the resolved jar information for each target and update the classpath
    # appropriately.
    classpath_products.add_excludes_for_targets(targets)
    for conf in confs:
      for target, resolved_jars in result.resolved_jars_for_each_target(conf, targets):
        classpath_products.add_jars_for_targets([target], conf, resolved_jars)

    return result.resolve_hash_name

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
      return _NO_RESOLVE_RUN_RESULT

    confs = confs or ('default',)
    extra_args = extra_args or []

    fingerprint_strategy = IvyResolveFingerprintStrategy(confs)

    # NB: See class pydoc regarding `use_cache=False`.
    with self.invalidated(targets,
                          invalidate_dependents=invalidate_dependents,
                          silent=silent,
                          fingerprint_strategy=fingerprint_strategy,
                          use_cache=False) as invalidation_check:
      # In case all the targets were filtered out because they didn't participate in fingerprinting.
      if not invalidation_check.all_vts:
        return _NO_RESOLVE_RUN_RESULT

      resolve_vts = VersionedTargetSet.from_versioned_targets(invalidation_check.all_vts)

      resolve_hash_name = resolve_vts.cache_key.hash

      ivy_workdir = os.path.join(self.context.options.for_global_scope().pants_workdir, 'ivy')
      resolve_workdir = os.path.join(ivy_workdir, resolve_hash_name)

      request = IvyResolveRequest(self.ivy_cache_dir,
                                  resolve_workdir,
                                  self.symlink_map_lock,
                                  resolve_hash_name,
                                  self.get_options().soft_excludes,
                                  confs)

      # Check for a previous run's resolution result files. If they exist try to load a result using
      # them. If that fails, fall back to doing a resolve and loading its results.
      if not invalidation_check.invalid_vts:
        result = IvyUtils.load_resolve(request, fatal=False)
        if result is not None:
          # Successfully loaded the previous resolve result.
          return result

      ivy = Bootstrapper.default_ivy(bootstrap_workunit_factory=self.context.new_workunit)
      IvyUtils.do_resolve(ivy,
                          executor,
                          extra_args,
                          resolve_vts,
                          pinned_artifacts,
                          workunit_name,
                          request)

      return IvyUtils.load_resolve(request)
