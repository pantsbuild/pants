# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import copy
import logging
import os
import shutil
import threading
from hashlib import sha1

from twitter.common.collections import maybe_list

from pants.backend.jvm.ivy_utils import IvyUtils
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.base.cache_manager import VersionedTargetSet
from pants.base.exceptions import TaskError
from pants.base.fingerprint_strategy import FingerprintStrategy
from pants.ivy.bootstrapper import Bootstrapper
from pants.ivy.ivy_subsystem import IvySubsystem
from pants.java.util import execute_runner
from pants.util.dirutil import safe_mkdir


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
      if target.payload.excludes or target.payload.configurations:
        hasher.update(target.payload.fingerprint(field_keys=('excludes', 'configurations')))
        return hasher.hexdigest()

    return None

  def __hash__(self):
    return hash((type(self), '-'.join(self._confs)))

  def __eq__(self, other):
    return type(self) == type(other) and self._confs == other._confs


class IvyTaskMixin(object):
  """A mixin for Tasks that execute resolves via Ivy.

  The creation of the 'ivy_resolve_symlink_map' product is a side effect of
  running `def ivy_resolve`. The product is a map of paths in Ivy's resolve cache to
  stable locations within the working copy. To consume the map, consume a parsed Ivy
  report which will give you IvyArtifact instances: the artifact path is key.
  """

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
    register('--automatic-excludes', action='store_true', default=True, advanced=True,
             help='If a target in the graph provides an artifact, said artifact will automatically '
                  'be excluded from Ivy resolution.')

  # Protect writes to the global map of jar path -> symlinks to that jar.
  symlink_map_lock = threading.Lock()

  # TODO(Eric Ayers): Change this method to relocate the resolution reports to under workdir
  # and return that path instead of having everyone know that these reports live under the
  # ivy cache dir.
  def ivy_resolve(self,
                  targets,
                  executor=None,
                  silent=False,
                  workunit_name=None,
                  confs=None,
                  custom_args=None):
    """Executes an ivy resolve for the relevant subset of the given targets.

    :returns: the resulting classpath, and the unique part of the name used for the resolution
    report (a hash). Also populates the 'ivy_resolve_symlink_map' product for jars resulting
    from the resolve."""

    if not targets:
      return ([], None)

    # NOTE: Always pass all the targets to exec_ivy, as they're used to calculate the name of
    # the generated module, which in turn determines the location of the XML report file
    # ivy generates. We recompute this name from targets later in order to find that file.
    # TODO: This is fragile. Refactor so that we're not computing the name twice.
    ivy = Bootstrapper.default_ivy(bootstrap_workunit_factory=self.context.new_workunit)

    ivy_workdir = os.path.join(self.context.options.for_global_scope().pants_workdir, 'ivy')

    fingerprint_strategy = IvyResolveFingerprintStrategy(confs)

    with self.invalidated(targets,
                          invalidate_dependents=False,
                          silent=silent,
                          fingerprint_strategy=fingerprint_strategy) as invalidation_check:
      if not invalidation_check.all_vts:
        return ([], None)
      global_vts = VersionedTargetSet.from_versioned_targets(invalidation_check.all_vts)

      # If a report file is not present, we need to exec ivy, even if all the individual
      # targets up to date... See https://rbcommons.com/s/twitter/r/2015
      report_missing = False
      report_confs = confs or ['default']
      report_paths = []
      resolve_hash_name = global_vts.cache_key.hash
      for conf in report_confs:
        report_path = IvyUtils.xml_report_path(resolve_hash_name, conf)
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
      if report_missing or invalidation_check.invalid_vts or not os.path.exists(raw_target_classpath_file):
        args = ['-cachepath', raw_target_classpath_file_tmp] + (custom_args if custom_args else [])

        self.exec_ivy(
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
          raise TaskError('Ivy failed to create classpath file at {}'
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
      products = self.context.products
      existing_symlinks_map = products.get_data('ivy_resolve_symlink_map', lambda: dict())
      symlink_map = IvyUtils.symlink_cachepath(
        IvySubsystem.global_instance().get_options().cache_dir,
        raw_target_classpath_file,
        symlink_dir,
        target_classpath_file,
        existing_symlinks_map)
      existing_symlinks_map.update(symlink_map)

    with IvyUtils.cachepath(target_classpath_file) as classpath:
      stripped_classpath = [path.strip() for path in classpath]
      return (stripped_classpath, resolve_hash_name)

  def mapjar_workdir(self, target):
    return os.path.join(self.workdir, 'mapped-jars', target.id)

  def mapjars(self, genmap, target, executor, jars=None):
    """Resolves jars for the target and stores their locations in genmap.

    :param genmap: The jar_dependencies ProductMapping entry for the required products.
    :param target: The target whose jar dependencies are being retrieved.
    :param jars: If specified, resolves the given jars rather than
    :type jars: List of :class:`pants.backend.jvm.targets.jar_dependency.JarDependency` (jar())
      objects.


     Here is an example of what the resulting genmap looks like after sucessfully mapping
     a JarLibrary target with a single JarDependency:

     ProductMapping(ivy_imports) {
      # target
      UnpackedJars(BuildFileAddress(.../unpack/BUILD, foo)) =>
          .../.pants.d/test/IvyImports/mapped-jars/unpack.foo/com.example/bar/default
        [u'com.example-bar-0.0.1.jar']
      # (org, name)
      (u'com.example', u'bar') =>
          .../.pants.d/test/IvyImports/mapped-jars/unpack.foo/com.example/bar/default
        [u'com.example-bar-0.0.1.jar']
      # (org)
      com.example => .../.pants.d/test/IvyImports/mapped-jars/unpack.foo/com.example/bar/default
        [u'com.example-bar-0.0.1.jar']
      # (target)
      (UnpackedJars(BuildFileAddress(.../unpack/BUILD, foo)), u'default') =>
          .../.pants.d/test/IvyImports/mapped-jars/unpack.foo/com.example/bar/default
        [u'com.example-bar-0.0.1.jar']
      # (org, name, conf)
      (u'com.example', u'bar', u'default') => .../.pants.d/test/IvyImports/mapped-jars/unpack.foo/com.example/bar/default
        [u'com.example-bar-0.0.1.jar']
    """
    mapdir = self.mapjar_workdir(target)
    safe_mkdir(mapdir, clean=True)
    ivyargs = [
      '-retrieve', '{}/[organisation]/[artifact]/[conf]/'
                   '[organisation]-[artifact]-[revision](-[classifier]).[ext]'.format(mapdir),
      '-symlink',
    ]
    confs = maybe_list(target.payload.get_field_value('configurations') or [])
    self.exec_ivy(mapdir,
                  [target],
                  executor=executor,
                  args=ivyargs,
                  confs=confs,
                  ivy=Bootstrapper.default_ivy(),
                  workunit_name='map-jars',
                  jars=jars,
                  use_soft_excludes=False)

    for org in os.listdir(mapdir):
      orgdir = os.path.join(mapdir, org)
      if os.path.isdir(orgdir):
        for name in os.listdir(orgdir):
          artifactdir = os.path.join(orgdir, name)
          if os.path.isdir(artifactdir):
            for conf in os.listdir(artifactdir):
              confdir = os.path.join(artifactdir, conf)
              for f in os.listdir(confdir):
                # TODO(John Sirois): kill the org and (org, name) exclude mappings in favor of a
                # conf whitelist
                genmap.add(org, confdir).append(f)
                genmap.add((org, name), confdir).append(f)

                genmap.add(target, confdir).append(f)
                genmap.add((target, conf), confdir).append(f)
                genmap.add((org, name, conf), confdir).append(f)

  def exec_ivy(self,
               target_workdir,
               targets,
               args,
               executor=None,
               confs=None,
               ivy=None,
               workunit_name='ivy',
               jars=None,
               use_soft_excludes=False,
               resolve_hash_name=None):
    ivy_jvm_options = copy.copy(self.get_options().jvm_options)
    # Disable cache in File.getCanonicalPath(), makes Ivy work with -symlink option properly on ng.
    ivy_jvm_options.append('-Dsun.io.useCanonCaches=false')

    ivy = ivy or Bootstrapper.default_ivy()
    ivyxml = os.path.join(target_workdir, 'ivy.xml')

    if not jars:
      automatic_excludes = self.get_options().automatic_excludes
      jars, excludes = IvyUtils.calculate_classpath(targets,
                                                    gather_excludes=not use_soft_excludes,
                                                    automatic_excludes=automatic_excludes)
    else:
      excludes = set()

    ivy_args = ['-ivy', ivyxml]

    confs_to_resolve = confs or ['default']
    ivy_args.append('-confs')
    ivy_args.extend(confs_to_resolve)
    ivy_args.extend(args)

    with IvyUtils.ivy_lock:
      IvyUtils.generate_ivy(targets, jars, excludes, ivyxml, confs_to_resolve, resolve_hash_name)
      runner = ivy.runner(jvm_options=ivy_jvm_options, args=ivy_args, executor=executor)
      try:
        result = execute_runner(runner, workunit_factory=self.context.new_workunit,
                                workunit_name=workunit_name)
        if result != 0:
          raise TaskError('Ivy returned {result}. cmd={cmd}'.format(result=result, cmd=runner.cmd))
      except runner.executor.Error as e:
        raise TaskError(e)
