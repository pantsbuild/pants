# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
import threading
from hashlib import sha1

from pants.backend.jvm.ivy_utils import IvyUtils
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
from pants.util.dirutil import safe_concurrent_creation, safe_mkdir
from pants.util.fileutil import atomic_copy
from pants.util.memo import memoized_property


_FULL_RESOLVE_IVY_XML_FILE_NAME = 'ivy.xml'

logger = logging.getLogger(__name__)


class IvyResolveResult(object):
  """The result of an Ivy resolution.

  The result data includes the list of resolved artifacts, the relationships between those artifacts
  and the targets that requested them and the hash name of the resolve.
  """

  def __init__(self, resolved_artifact_paths, symlink_map, resolve_hash_name, reports_by_conf):
    self._reports_by_conf = reports_by_conf
    self.resolved_artifact_paths = resolved_artifact_paths
    self.resolve_hash_name = resolve_hash_name
    self._symlink_map = symlink_map

  @property
  def has_resolved_artifacts(self):
    """The requested targets have a resolution associated with them."""
    return self.resolve_hash_name is not None

  def all_linked_artifacts_exist(self):
    """All of the artifact paths for this resolve point to existing files."""
    for path in self.resolved_artifact_paths:
      if not os.path.isfile(path):
        return False
    else:
      return True

  def resolved_jars_for_each_target(self, conf, targets):
    """Yields the resolved jars for each passed JarLibrary.

    If there is no report for the requested conf, yields nothing.

    :param conf: The ivy conf to load targets for.
    :param targets: The collection of JarLibrary targets to find resolved jars for.
    :yield: target, resolved_jars
    :raises IvyTaskMixin.UnresolvedJarError
    """
    ivy_info = self._ivy_info_for(conf)
    if not ivy_info:
      return

    jar_library_targets = [t for t in targets if isinstance(t, JarLibrary)]
    ivy_jar_memo = {}
    for target in jar_library_targets:
      # Add the artifacts from each dependency module.
      resolved_jars = self._resolved_jars_with_symlinks(conf, ivy_info, ivy_jar_memo,
                                               target.jar_dependencies, target)
      yield target, resolved_jars

  def _ivy_info_for(self, conf):
    report_path = self._reports_by_conf.get(conf)
    return IvyUtils.parse_xml_report(conf, report_path)

  def _new_resolved_jar_with_symlink_path(self, conf, tgt, resolved_jar_without_symlink):
    def candidate_cache_paths():
      # There is a focus on being lazy here to avoid `os.path.realpath` when we can.
      yield resolved_jar_without_symlink.cache_path
      yield os.path.realpath(resolved_jar_without_symlink.cache_path)

    for cache_path in candidate_cache_paths():
      pants_path = self._symlink_map.get(cache_path)
      if pants_path:
        break
    else:
      raise IvyTaskMixin.UnresolvedJarError(
        'Jar {resolved_jar} in {spec} not resolved to the ivy '
        'symlink map in conf {conf}.'
        .format(spec=tgt.address.spec,
                resolved_jar=resolved_jar_without_symlink.cache_path,
                conf=conf))

    return ResolvedJar(coordinate=resolved_jar_without_symlink.coordinate,
                       pants_path=pants_path,
                       cache_path=resolved_jar_without_symlink.cache_path)

  def _resolved_jars_with_symlinks(self, conf, ivy_info, ivy_jar_memo, coordinates, target):
    raw_resolved_jars = ivy_info.get_resolved_jars_for_coordinates(coordinates,
                                                                   memo=ivy_jar_memo)
    resolved_jars = [self._new_resolved_jar_with_symlink_path(conf, target, raw_resolved_jar)
                     for raw_resolved_jar in raw_resolved_jars]
    return resolved_jars


_NO_RESOLVE_RUN_RESULT = IvyResolveResult([], {}, None, None)


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

      symlink_classpath_filename = os.path.join(resolve_workdir, 'classpath')
      ivy_cache_classpath_filename = symlink_classpath_filename + '.raw'

      workdir_reports_by_conf = {c: self._resolve_report_path(resolve_workdir, c) for c in confs}

      def resolve_result_files_exist():
        return (all(os.path.isfile(report) for report in workdir_reports_by_conf.values()) and
                os.path.isfile(ivy_cache_classpath_filename))

      # Check for a previous run's resolution result files. If they exist try to load a result using
      # them. If that fails, fall back to doing a resolve and loading its results.
      if not invalidation_check.invalid_vts and resolve_result_files_exist():
        result = self._load_from_resolve(ivy_cache_classpath_filename, symlink_classpath_filename,
                                          ivy_workdir, resolve_hash_name, workdir_reports_by_conf)
        if result.all_linked_artifacts_exist():
          return result

      self._do_resolve(confs, executor, extra_args, resolve_vts, pinned_artifacts,
                            ivy_cache_classpath_filename,
                            resolve_hash_name, resolve_workdir, workunit_name)

      return self._load_from_resolve(ivy_cache_classpath_filename,
                                     symlink_classpath_filename,
                                     ivy_workdir,
                                     resolve_hash_name,
                                     workdir_reports_by_conf)

  def _load_from_resolve(self, ivy_cache_classpath_filename, symlink_classpath_filename,
                              ivy_workdir, resolve_hash_name, reports_by_conf):
    symlink_map = self._symlink_from_cache_path(self.ivy_cache_dir, ivy_workdir,
                                                ivy_cache_classpath_filename,
                                                symlink_classpath_filename)
    resolved_artifact_paths = IvyUtils.load_classpath_from_cachepath(symlink_classpath_filename)
    return IvyResolveResult(resolved_artifact_paths,
                            symlink_map,
                            resolve_hash_name,
                            reports_by_conf)

  def _do_resolve(self, confs, executor, extra_args, global_vts, pinned_artifacts,
                       raw_target_classpath_file, resolve_hash_name, resolve_workdir,
                       workunit_name):
    safe_mkdir(resolve_workdir)
    ivy = Bootstrapper.default_ivy(bootstrap_workunit_factory=self.context.new_workunit)

    with safe_concurrent_creation(raw_target_classpath_file) as raw_target_classpath_file_tmp:
      args = ['-cachepath', raw_target_classpath_file_tmp] + extra_args

      targets = global_vts.targets
      # TODO(John Sirois): merge the code below into IvyUtils or up here; either way, better
      # diagnostics can be had in `IvyUtils.generate_ivy` if this is done.
      # See: https://github.com/pantsbuild/pants/issues/2239
      jars, global_excludes = IvyUtils.calculate_classpath(targets)

      # Don't pass global excludes to ivy when using soft excludes.
      if self.get_options().soft_excludes:
        global_excludes = []

      ivyxml = self._ivy_xml_path(resolve_workdir)
      with IvyUtils.ivy_lock:
        try:
          IvyUtils.generate_ivy(targets, jars, global_excludes, ivyxml, confs,
                                resolve_hash_name, pinned_artifacts)
        except IvyUtils.IvyError as e:
          raise self.Error('Failed to prepare ivy resolve: {}'.format(e))

        self._exec_ivy(ivy, executor, confs, ivyxml, args, workunit_name)

        # Copy ivy resolve file into resolve workdir.
        for conf in confs:
          atomic_copy(IvyUtils.xml_report_path(self.ivy_cache_dir, resolve_hash_name, conf),
                      self._resolve_report_path(resolve_workdir, conf))

      if not os.path.exists(raw_target_classpath_file_tmp):
        raise self.Error('Ivy failed to create classpath file at {}'
                         .format(raw_target_classpath_file_tmp))

    logger.debug('Moved ivy classfile file to {dest}'.format(dest=raw_target_classpath_file))

  def _resolve_report_path(self, resolve_workdir, conf):
    return os.path.join(resolve_workdir, 'resolve-report-{}.xml'.format(conf))

  def _ivy_xml_path(self, resolve_workdir):
    return os.path.join(resolve_workdir, _FULL_RESOLVE_IVY_XML_FILE_NAME)

  def _symlink_from_cache_path(self, ivy_cache_dir, ivy_workdir, raw_target_classpath_file,
                               target_classpath_file):
    # Make our actual classpath be symlinks, so that the paths are uniform across systems.
    # Note that we must do this even if we read the raw_target_classpath_file from the artifact
    # cache. If we cache the target_classpath_file we won't know how to create the symlinks.
    with IvyTaskMixin.symlink_map_lock:
      # A common dir for symlinks into the ivy2 cache. This ensures that paths to jars
      # in artifact-cached analysis files are consistent across systems.
      # Note that we have one global, well-known symlink dir, again so that paths are
      # consistent across builds.
      symlink_dir = os.path.join(ivy_workdir, 'jars')
      symlink_map = IvyUtils.symlink_cachepath(ivy_cache_dir,
                                               raw_target_classpath_file,
                                               symlink_dir,
                                               target_classpath_file)
    return symlink_map

  def _exec_ivy(self, ivy, executor, confs, ivyxml, args, workunit_name):
    try:
      IvyUtils.exec_ivy(ivy, confs, ivyxml, args,
                        jvm_options=self.get_options().jvm_options,
                        executor=executor,
                        workunit_name=workunit_name,
                        workunit_factory=self.context.new_workunit)
    except IvyUtils.IvyError as e:
      raise self.Error('Ivy resolve failed: {}'.format(e))
