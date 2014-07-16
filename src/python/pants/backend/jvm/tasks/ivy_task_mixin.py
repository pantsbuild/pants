# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from collections import defaultdict
from hashlib import sha1
import os
import shutil
import threading

from pants.backend.jvm.ivy_utils import IvyUtils
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.base.cache_manager import VersionedTargetSet
from pants.base.exceptions import TaskError
from pants.base.fingerprint_strategy import FingerprintStrategy
from pants.ivy.bootstrapper import Bootstrapper
from pants.java.executor import Executor


class IvyResolveFingerprintStrategy(FingerprintStrategy):
  @classmethod
  def name(cls):
    return 'ivy_resolve'

  @classmethod
  def product_types(cls):
    return ['symlink_map']

  def compute_fingerprint(self, target):
    if isinstance(target, JarLibrary):
      return target.payload.invalidation_hash()
    elif isinstance(target, JvmTarget):
      hasher = sha1()
      for exclude in sorted(target.payload.excludes):
        hasher.update(bytes(repr(exclude)))
      for config in sorted(target.payload.configurations):
        hasher.update(config)
      return hasher.hexdigest()
    else:
      return sha1().hexdigest()


class IvyTaskMixin(object):
  # Protect writes to the global map of jar path -> symlinks to that jar.
  symlink_map_lock = threading.Lock()

  def ivy_resolve(self,
                  targets,
                  executor=None,
                  symlink_ivyxml=False,
                  silent=False,
                  workunit_name=None,
                  workunit_labels=None):
    # NOTE: Always pass all the targets to exec_ivy, as they're used to calculate the name of
    # the generated module, which in turn determines the location of the XML report file
    # ivy generates. We recompute this name from targets later in order to find that file.
    # TODO: This is fragile. Refactor so that we're not computing the name twice.
    if executor and not isinstance(executor, Executor):
      raise ValueError('The executor must be an Executor instance, given %s of type %s'
                       % (executor, type(executor)))
    ivy = Bootstrapper.default_ivy(java_executor=executor,
                                   bootstrap_workunit_factory=self.context.new_workunit)
    if not targets:
      return []

    ivy_workdir = os.path.join(self.context.config.getdefault('pants_workdir'), 'ivy')
    ivy_utils = IvyUtils(config=self.context.config,
                         options=self.context.options,
                         log=self.context.log)

    fingerprint_strategy = IvyResolveFingerprintStrategy()

    with self.invalidated(targets,
                          invalidate_dependents=True,
                          silent=silent,
                          fingerprint_strategy=fingerprint_strategy) as invalidation_check:
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
          ivy_utils.exec_ivy(
              target_workdir=target_workdir,
              targets=targets,
              args=args,
              ivy=ivy,
              workunit_name='ivy',
              workunit_factory=self.context.new_workunit,
              symlink_ivyxml=symlink_ivyxml)

        if workunit_name:
          with self.context.new_workunit(name=workunit_name, labels=workunit_labels or []):
            exec_ivy()
        else:
          exec_ivy()

        if not os.path.exists(raw_target_classpath_file_tmp):
          raise TaskError('Ivy failed to create classpath file at %s'
                          % raw_target_classpath_file_tmp)
        shutil.move(raw_target_classpath_file_tmp, raw_target_classpath_file)

        if self.artifact_cache_writes_enabled():
          self.update_artifact_cache([(global_vts, [raw_target_classpath_file])])

    # Make our actual classpath be symlinks, so that the paths are uniform across systems.
    # Note that we must do this even if we read the raw_target_classpath_file from the artifact
    # cache. If we cache the target_classpath_file we won't know how to create the symlinks.
    symlink_map = IvyUtils.symlink_cachepath(self.context.ivy_home, raw_target_classpath_file,
                                             symlink_dir, target_classpath_file)
    with IvyTaskMixin.symlink_map_lock:
      all_symlinks_map = self.context.products.get_data('symlink_map') or defaultdict(list)
      for path, symlink in symlink_map.items():
        all_symlinks_map[os.path.realpath(path)].append(symlink)
      self.context.products.safe_create_data('symlink_map', lambda: all_symlinks_map)

    with IvyUtils.cachepath(target_classpath_file) as classpath:
      stripped_classpath = [path.strip() for path in classpath]
      return [path for path in stripped_classpath if ivy_utils.is_classpath_artifact(path)]
