# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
import shutil
import threading
from hashlib import sha1

from pants.backend.core.tasks.task import TaskBase
from pants.backend.jvm.ivy_utils import IvyUtils
from pants.backend.jvm.jar_dependency_utils import ResolvedJar
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.base.exceptions import TaskError
from pants.base.fingerprint_strategy import FingerprintStrategy
from pants.invalidation.cache_manager import VersionedTargetSet
from pants.ivy.bootstrapper import Bootstrapper
from pants.ivy.ivy_subsystem import IvySubsystem
from pants.java.util import execute_runner
from pants.util.memo import memoized_property


logger = logging.getLogger(__name__)


class IvyResolveFingerprintStrategy(FingerprintStrategy):

  def __init__(self, confs):
    super(IvyResolveFingerprintStrategy, self).__init__()
    self._confs = sorted(confs or [])

  def compute_fingerprint(self, target):
    hasher = sha1()
    for conf in self._confs:
      hasher.update(conf)
    if isinstance(target, JarLibrary):
      hasher.update(target.payload.fingerprint())
      return hasher.hexdigest()
    if isinstance(target, JvmTarget):
      if target.payload.excludes:
        hasher.update(target.payload.fingerprint(field_keys=('excludes',)))
        return hasher.hexdigest()

    return None

  def __hash__(self):
    return hash((type(self), '-'.join(self._confs)))

  def __eq__(self, other):
    return type(self) == type(other) and self._confs == other._confs


class IvyTaskMixin(TaskBase):
  """A mixin for Tasks that execute resolves via Ivy."""

  class Error(TaskError):
    """Indicates an error performing an ivy resolve."""

  class UnresolvedJarError(Error):
    """Indicates a jar dependency couldn't be mapped."""

  @classmethod
  def global_subsystems(cls):
    return super(IvyTaskMixin, cls).global_subsystems() + (IvySubsystem, )

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

  @memoized_property
  def ivy_cache_dir(self):
    """The path of the ivy cache dir used for resolves.

    :rtype: string
    """
    # TODO(John Sirois): Fixup the IvySubsystem to encapsulate its properties.
    return IvySubsystem.global_instance().get_options().cache_dir

  def resolve(self, executor, targets, classpath_products, confs=None, extra_args=None,
              invalidate_dependents=False):
    """Resolves external classpath products (typically jars) for the given targets.

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
    :returns: The id of the reports associated with this resolve.
    :rtype: string
    """

    classpath_products.add_excludes_for_targets(targets)

    confs = confs or ('default',)

    # After running ivy, we parse the resulting report, and record the dependencies for
    # all relevant targets (ie: those that have direct dependencies).
    _, symlink_map, resolve_hash_name = self.ivy_resolve(
      targets,
      executor=executor,
      workunit_name='ivy-resolve',
      confs=confs,
      custom_args=extra_args,
      invalidate_dependents=invalidate_dependents,
    )

    if not resolve_hash_name:
      # There was no resolve to do, so no 3rdparty deps to process below
      return

    # Record the ordered subset of jars that each jar_library/leaf depends on using
    # stable symlinks within the working copy.

    def new_resolved_jar_with_symlink_path(tgt, cnf, resolved_jar_without_symlink):
      # There is a focus on being lazy here to avoid `os.path.realpath` when we can.
      def candidate_cache_paths():
        yield resolved_jar_without_symlink.cache_path
        yield os.path.realpath(resolved_jar_without_symlink.cache_path)

      try:
        return next(ResolvedJar(coordinate=resolved_jar_without_symlink.coordinate,
                                pants_path=symlink_map[cache_path],
                                cache_path=resolved_jar_without_symlink.cache_path)
                    for cache_path in candidate_cache_paths() if cache_path in symlink_map)
      except StopIteration:
        raise self.UnresolvedJarError('Jar {resolved_jar} in {spec} not resolved to the ivy '
                                      'symlink map in conf {conf}.'
                                      .format(spec=tgt.address.spec,
                                              resolved_jar=resolved_jar_without_symlink.cache_path,
                                              conf=cnf))

    # Build the 3rdparty classpath product.
    for conf in confs:
      ivy_info = self._parse_report(resolve_hash_name, conf)
      if not ivy_info:
        continue
      ivy_jar_memo = {}
      jar_library_targets = [t for t in targets if isinstance(t, JarLibrary)]
      for target in jar_library_targets:
        # Add the artifacts from each dependency module.
        raw_resolved_jars = ivy_info.get_resolved_jars_for_jar_library(target, memo=ivy_jar_memo)
        resolved_jars = [new_resolved_jar_with_symlink_path(target, conf, raw_resolved_jar)
                         for raw_resolved_jar in raw_resolved_jars]
        classpath_products.add_jars_for_targets([target], conf, resolved_jars)

    return resolve_hash_name

  # Extracted for testing.
  def _parse_report(self, resolve_hash_name, conf):
    return IvyUtils.parse_xml_report(self.ivy_cache_dir, resolve_hash_name, conf)

  # TODO(Eric Ayers): Change this method to relocate the resolution reports to under workdir
  # and return that path instead of having everyone know that these reports live under the
  # ivy cache dir.
  def ivy_resolve(self,
                  targets,
                  executor=None,
                  silent=False,
                  workunit_name=None,
                  confs=None,
                  custom_args=None,
                  invalidate_dependents=False):
    """Resolves external dependencies for the given targets.

    If there are no targets suitable for jvm transitive dependency resolution, an empty result is
    returned, ie: ([], {}, None).

    :param targets: The targets to resolve jvm dependencies for.
    :type targets: :class:`collections.Iterable` of :class:`pants.build_graph.target.Target`
    :param executor: A java executor to run ivy with.
    :type executor: :class:`pants.java.executor.Executor`

    :param confs: The ivy configurations to resolve; ('default',) by default.
    :type confs: :class:`collections.Iterable` of string
    :param custom_args: Any extra command line arguments to pass to ivy.
    :type custom_args: list of string
    :param bool invalidate_dependents: `True` to invalidate dependents of targets that needed to be
                                        resolved.
    :returns: A tuple of the classpath, a mapping from ivy cache jars to their linked location
              under .pants.d, and the id of the reports associated with the resolve.
    :rtype: tuple of (list, dict, string)
    """
    if not targets:
      return [], {}, None

    ivy = Bootstrapper.default_ivy(bootstrap_workunit_factory=self.context.new_workunit)

    ivy_workdir = os.path.join(self.context.options.for_global_scope().pants_workdir, 'ivy')

    fingerprint_strategy = IvyResolveFingerprintStrategy(confs)

    with self.invalidated(targets,
                          invalidate_dependents=invalidate_dependents,
                          silent=silent,
                          fingerprint_strategy=fingerprint_strategy) as invalidation_check:
      if not invalidation_check.all_vts:
        return [], {}, None
      global_vts = VersionedTargetSet.from_versioned_targets(invalidation_check.all_vts)

      # If a report file is not present, we need to exec ivy, even if all the individual
      # targets up to date... See https://rbcommons.com/s/twitter/r/2015
      report_missing = False
      report_confs = confs or ['default']
      report_paths = []
      resolve_hash_name = global_vts.cache_key.hash
      for conf in report_confs:
        report_path = IvyUtils.xml_report_path(self.ivy_cache_dir, resolve_hash_name, conf)
        if not os.path.exists(report_path):
          report_missing = True
          break
        else:
          report_paths.append(report_path)
      target_workdir = os.path.join(ivy_workdir, resolve_hash_name)
      target_classpath_file = os.path.join(target_workdir, 'classpath')
      raw_target_classpath_file = target_classpath_file + '.raw'
      raw_target_classpath_file_tmp = raw_target_classpath_file + '.tmp'
      # A common dir for symlinks into the ivy2 cache. This ensures that paths to jars
      # in artifact-cached analysis files are consistent across systems.
      # Note that we have one global, well-known symlink dir, again so that paths are
      # consistent across builds.
      symlink_dir = os.path.join(ivy_workdir, 'jars')

      # Note that it's possible for all targets to be valid but for no classpath file to exist at
      # target_classpath_file, e.g., if we previously built a superset of targets.
      if (report_missing or
          invalidation_check.invalid_vts or
          not os.path.exists(raw_target_classpath_file)):
        args = ['-cachepath', raw_target_classpath_file_tmp] + (custom_args if custom_args else [])

        self._exec_ivy(
            target_workdir=target_workdir,
            targets=global_vts.targets,
            args=args,
            executor=executor,
            ivy=ivy,
            workunit_name=workunit_name,
            confs=confs,
            use_soft_excludes=self.get_options().soft_excludes,
            resolve_hash_name=resolve_hash_name)

        if not os.path.exists(raw_target_classpath_file_tmp):
          raise self.Error('Ivy failed to create classpath file at {}'
                           .format(raw_target_classpath_file_tmp))
        shutil.move(raw_target_classpath_file_tmp, raw_target_classpath_file)
        logger.debug('Moved ivy classfile file to {dest}'.format(dest=raw_target_classpath_file))

        if self.artifact_cache_writes_enabled():
          self.update_artifact_cache([(global_vts, [raw_target_classpath_file])])
      else:
        logger.debug("Using previously resolved reports: {}".format(report_paths))

    # Make our actual classpath be symlinks, so that the paths are uniform across systems.
    # Note that we must do this even if we read the raw_target_classpath_file from the artifact
    # cache. If we cache the target_classpath_file we won't know how to create the symlinks.
    with IvyTaskMixin.symlink_map_lock:
      symlink_map = IvyUtils.symlink_cachepath(self.ivy_cache_dir,
                                               raw_target_classpath_file,
                                               symlink_dir,
                                               target_classpath_file)

      with IvyUtils.cachepath(target_classpath_file) as classpath:
        stripped_classpath = [path.strip() for path in classpath]
        return stripped_classpath, symlink_map, resolve_hash_name

  def _exec_ivy(self,
               target_workdir,
               targets,
               args,
               executor=None,
               confs=None,
               ivy=None,
               workunit_name='ivy',
               use_soft_excludes=False,
               resolve_hash_name=None):
    ivy_jvm_options = self.get_options().jvm_options[:]
    # Disable cache in File.getCanonicalPath(), makes Ivy work with -symlink option properly on ng.
    ivy_jvm_options.append('-Dsun.io.useCanonCaches=false')

    ivy = ivy or Bootstrapper.default_ivy()
    ivyxml = os.path.join(target_workdir, 'ivy.xml')

    ivy_args = ['-ivy', ivyxml]

    confs_to_resolve = confs or ('default',)
    ivy_args.append('-confs')
    ivy_args.extend(confs_to_resolve)
    ivy_args.extend(args)

    # TODO(John Sirois): merge the code below into IvyUtils or up here; either way, better
    # diagnostics can be had in `IvyUtils.generate_ivy` if this is done.
    # See: https://github.com/pantsbuild/pants/issues/2239
    try:
      jars, excludes = IvyUtils.calculate_classpath(targets, gather_excludes=not use_soft_excludes)
      with IvyUtils.ivy_lock:
        IvyUtils.generate_ivy(targets, jars, excludes, ivyxml, confs_to_resolve, resolve_hash_name)
        runner = ivy.runner(jvm_options=ivy_jvm_options, args=ivy_args, executor=executor)
        try:
          result = execute_runner(runner, workunit_factory=self.context.new_workunit,
                                  workunit_name=workunit_name)
          if result != 0:
            raise self.Error('Ivy returned {result}. cmd={cmd}'.format(result=result, cmd=runner.cmd))
        except runner.executor.Error as e:
          raise self.Error(e)
    except IvyUtils.IvyError as e:
      raise self.Error('Failed to prepare ivy resolve: {}'.format(e))
