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
from collections import defaultdict

from twitter.common.collections import maybe_list

from pants.backend.jvm.ivy_utils import IvyUtils
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.base.cache_manager import VersionedTargetSet
from pants.base.exceptions import TaskError
from pants.base.fingerprint_strategy import DefaultFingerprintHashingMixin, FingerprintStrategy
from pants.ivy.bootstrapper import Bootstrapper
from pants.java.util import execute_runner
from pants.util.dirutil import safe_mkdir


logger = logging.getLogger(__name__)


class IvyResolveFingerprintStrategy(DefaultFingerprintHashingMixin, FingerprintStrategy):

  def compute_fingerprint(self, target):
    if isinstance(target, JarLibrary):
      return target.payload.fingerprint()
    if isinstance(target, JvmTarget):
      if target.payload.excludes or target.payload.configurations:
        return target.payload.fingerprint(field_keys=('excludes', 'configurations'))
    return None



class IvyTaskMixin(object):
  @classmethod
  def register_options(cls, register):
    super(IvyTaskMixin, cls).register_options(register)
    register('--jvm-options', action='append', metavar='<option>...',
             help='Run Ivy with these extra jvm options.')

  # Protect writes to the global map of jar path -> symlinks to that jar.
  symlink_map_lock = threading.Lock()

  def ivy_resolve(self,
                  targets,
                  executor=None,
                  silent=False,
                  workunit_name=None,
                  confs=None,
                  custom_args=None):
    """Populates the product 'ivy_resolve_symlink_map' from the specified targets."""

    if not targets:
      return ([], set())

    # NOTE: Always pass all the targets to exec_ivy, as they're used to calculate the name of
    # the generated module, which in turn determines the location of the XML report file
    # ivy generates. We recompute this name from targets later in order to find that file.
    # TODO: This is fragile. Refactor so that we're not computing the name twice.
    ivy = Bootstrapper.default_ivy(bootstrap_workunit_factory=self.context.new_workunit)

    ivy_workdir = os.path.join(self.context.options.for_global_scope().pants_workdir, 'ivy')

    fingerprint_strategy = IvyResolveFingerprintStrategy()

    with self.invalidated(targets,
                          invalidate_dependents=False,
                          silent=silent,
                          fingerprint_strategy=fingerprint_strategy) as invalidation_check:
      if not invalidation_check.all_vts:
        return ([], set())
      global_vts = VersionedTargetSet.from_versioned_targets(invalidation_check.all_vts)
      target_workdir = os.path.join(ivy_workdir, global_vts.cache_key.hash)
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
      if invalidation_check.invalid_vts or not os.path.exists(raw_target_classpath_file):
        args = ['-cachepath', raw_target_classpath_file_tmp] + (custom_args if custom_args else [])

        self.exec_ivy(
            target_workdir=target_workdir,
            targets=global_vts.targets,
            args=args,
            executor=executor,
            ivy=ivy,
            workunit_name=workunit_name,
            confs=confs)

        if not os.path.exists(raw_target_classpath_file_tmp):
          raise TaskError('Ivy failed to create classpath file at %s'
                          % raw_target_classpath_file_tmp)
        shutil.move(raw_target_classpath_file_tmp, raw_target_classpath_file)
        logger.debug('Copied ivy classfile file to {dest}'.format(dest=raw_target_classpath_file))

        if self.artifact_cache_writes_enabled():
          self.update_artifact_cache([(global_vts, [raw_target_classpath_file])])

    # Make our actual classpath be symlinks, so that the paths are uniform across systems.
    # Note that we must do this even if we read the raw_target_classpath_file from the artifact
    # cache. If we cache the target_classpath_file we won't know how to create the symlinks.
    symlink_map = IvyUtils.symlink_cachepath(ivy.ivy_cache_dir, raw_target_classpath_file,
                                             symlink_dir, target_classpath_file)
    with IvyTaskMixin.symlink_map_lock:
      products = self.context.products
      all_symlinks_map = products.get_data('ivy_resolve_symlink_map') or defaultdict(list)
      for path, symlink in symlink_map.items():
        all_symlinks_map[os.path.realpath(path)].append(symlink)
      products.safe_create_data('ivy_resolve_symlink_map',
                                lambda: all_symlinks_map)

    with IvyUtils.cachepath(target_classpath_file) as classpath:
      stripped_classpath = [path.strip() for path in classpath]
      return (stripped_classpath, global_vts.targets)

  def mapjars(self, genmap, target, executor, jars=None):
    """Resolves jars for the target and stores their locations in genmap.

    :param genmap: The jar_dependencies ProductMapping entry for the required products.
    :param target: The target whose jar dependencies are being retrieved.
    :param jars: If specified, resolves the given jars rather than
    :type jars: List of :class:`pants.backend.jvm.targets.jar_dependency.JarDependency` (jar())
      objects.
    """
    mapdir = os.path.join(self.workdir, 'mapped-jars', target.id)
    safe_mkdir(mapdir, clean=True)
    ivyargs = [
      '-retrieve', '%s/[organisation]/[artifact]/[conf]/'
                   '[organisation]-[artifact]-[revision](-[classifier]).[ext]' % mapdir,
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
                  jars=jars)

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
               jars=None):
    ivy_jvm_options = copy.copy(self.get_options().jvm_options)
    # Disable cache in File.getCanonicalPath(), makes Ivy work with -symlink option properly on ng.
    ivy_jvm_options.append('-Dsun.io.useCanonCaches=false')

    ivy = ivy or Bootstrapper.default_ivy()
    ivyxml = os.path.join(target_workdir, 'ivy.xml')

    if not jars:
      jars, excludes = IvyUtils.calculate_classpath(targets)
    else:
      excludes = set()

    ivy_args = ['-ivy', ivyxml]

    confs_to_resolve = confs or ['default']
    ivy_args.append('-confs')
    ivy_args.extend(confs_to_resolve)
    ivy_args.extend(args)

    with IvyUtils.ivy_lock:
      IvyUtils.generate_ivy(targets, jars, excludes, ivyxml, confs_to_resolve)
      runner = ivy.runner(jvm_options=ivy_jvm_options, args=ivy_args, executor=executor)
      try:
        result = execute_runner(runner, workunit_factory=self.context.new_workunit,
                                workunit_name=workunit_name)
        if result != 0:
          raise TaskError('Ivy returned %d' % result)
      except runner.executor.Error as e:
        raise TaskError(e)
