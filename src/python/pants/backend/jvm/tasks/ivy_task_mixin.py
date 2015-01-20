# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from collections import defaultdict
import logging
import os
import shutil
import threading

from twitter.common.collections import maybe_list

from pants.backend.jvm.ivy_utils import IvyUtils
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.base.cache_manager import VersionedTargetSet
from pants.base.exceptions import TaskError
from pants.base.fingerprint_strategy import FingerprintStrategy
from pants.ivy.bootstrapper import Bootstrapper
from pants.java.executor import Executor
from pants.util.dirutil import safe_mkdir

logger = logging.getLogger(__name__)


class IvyResolveFingerprintStrategy(FingerprintStrategy):
  @classmethod
  def product_types(cls):
    # TODO(pl): This is almost certainly supposed to be on IvyTaskMixin,
    # but it might mess up MRO linearization.
    # It seems to be completely unused right now.
    return ['symlink_map']

  def compute_fingerprint(self, target):
    if isinstance(target, JarLibrary):
      return target.payload.fingerprint()
    elif isinstance(target, JvmTarget):
      if target.payload.excludes or target.payload.configurations:
        return target.payload.fingerprint(field_keys=('excludes', 'configurations'))
      else:
        return None
    else:
      return None

  def __hash__(self):
    return hash(type(self))

  def __eq__(self, other):
    return type(self) == type(other)


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
                  workunit_labels=None):
    if not targets:
      return ([], set())

    # NOTE: Always pass all the targets to exec_ivy, as they're used to calculate the name of
    # the generated module, which in turn determines the location of the XML report file
    # ivy generates. We recompute this name from targets later in order to find that file.
    # TODO: This is fragile. Refactor so that we're not computing the name twice.
    if executor and not isinstance(executor, Executor):
      raise ValueError('The executor must be an Executor instance, given %s of type %s'
                       % (executor, type(executor)))
    ivy = Bootstrapper.default_ivy(java_executor=executor,
                                   bootstrap_workunit_factory=self.context.new_workunit)

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
        args = ['-cachepath', raw_target_classpath_file_tmp]

        def exec_ivy():
          IvyUtils.exec_ivy(
              target_workdir=target_workdir,
              targets=global_vts.targets,
              args=args,
              jvm_options=self.get_options().jvm_options,
              ivy=ivy,
              workunit_name='ivy',
              workunit_factory=self.context.new_workunit)

        if workunit_name:
          with self.context.new_workunit(name=workunit_name, labels=workunit_labels or []):
            exec_ivy()
        else:
          exec_ivy()

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
      all_symlinks_map = self.context.products.get_data('symlink_map') or defaultdict(list)
      for path, symlink in symlink_map.items():
        all_symlinks_map[os.path.realpath(path)].append(symlink)
      self.context.products.safe_create_data('symlink_map', lambda: all_symlinks_map)

    with IvyUtils.cachepath(target_classpath_file) as classpath:
      stripped_classpath = [path.strip() for path in classpath]
      return ([path for path in stripped_classpath if self.is_classpath_artifact(path)],
              global_vts.targets)

  @staticmethod
  def is_classpath_artifact(path):
    """Subclasses can override to determine whether a given artifact represents a classpath
    artifact."""
    return path.endswith('.jar') or path.endswith('.war')

  def mapjars(self, genmap, target, executor, workunit_factory=None, jars=None):
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
    confs = target.payload.get_field_value('configurations') or []
    IvyUtils.exec_ivy(mapdir,
                      [target],
                      jvm_options=self.get_options().jvm_options,
                      args=ivyargs,
                      confs=maybe_list(confs),
                      ivy=Bootstrapper.default_ivy(executor),
                      workunit_factory=workunit_factory,
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
                if self.is_classpath_artifact(f):
                  # TODO(John Sirois): kill the org and (org, name) exclude mappings in favor of a
                  # conf whitelist
                  genmap.add(org, confdir).append(f)
                  genmap.add((org, name), confdir).append(f)

                  genmap.add(target, confdir).append(f)
                  genmap.add((target, conf), confdir).append(f)
                  genmap.add((org, name, conf), confdir).append(f)

