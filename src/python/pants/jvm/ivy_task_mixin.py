# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
import shutil
import threading

from collections import defaultdict, namedtuple

from pants.base.cache_manager import VersionedTargetSet
from pants.base.exceptions import TaskError
from pants.ivy.bootstrapper import Bootstrapper
from pants.java.executor import Executor
from pants.jvm.ivy_utils import IvyUtils


ResolveResult = namedtuple('ResolveResult', ['classpath', 'raw_classpath_file', 'updated'])


def _ivy_workdir(context):
  return os.path.join(context.config.getdefault('pants_workdir'), 'ivy')


# Protect writes to the global map of jar path -> symlinks to that jar.
_SYMLINK_MAP_LOCK = threading.Lock()


def _resolve(context,
             target_workdir,
             targets,
             ivy=None,
             symlink_ivyxml=False,
             workunit_name=None,
             workunit_labels=None):

  targets = set(targets)
  if not targets:
    return ResolveResult(classpath=[], raw_classpath_file=None, updated=False)

  ivy_workdir = _ivy_workdir(context)

  # A common dir for symlinks into the ivy2 cache. This ensures that paths to jars
  # in artifact-cached analysis files are consistent across systems.
  # Note that we have one global, well-known symlink dir, again so that paths are
  # consistent across builds.
  symlink_dir = os.path.join(ivy_workdir, 'jars')

  target_classpath_file = os.path.join(target_workdir, 'classpath')
  raw_target_classpath_file = target_classpath_file + '.raw'

  updated = False

  if not os.path.exists(raw_target_classpath_file):
    ivy_utils = IvyUtils(config=context.config,
                         options=context.options,
                         log=context.log)

    raw_target_classpath_file_tmp = raw_target_classpath_file + '.tmp'
    args = ['-cachepath', raw_target_classpath_file_tmp]

    def exec_ivy():
      ivy_utils.exec_ivy(
          target_workdir=target_workdir,
          targets=targets,
          args=args,
          ivy=ivy,
          workunit_name='ivy',
          workunit_factory=context.new_workunit,
          symlink_ivyxml=symlink_ivyxml)

    if workunit_name:
      with context.new_workunit(name=workunit_name, labels=workunit_labels or []):
        exec_ivy()
    else:
      exec_ivy()

    if not os.path.exists(raw_target_classpath_file_tmp):
      raise TaskError('Ivy failed to create classpath file at %s'
                      % raw_target_classpath_file_tmp)
    shutil.move(raw_target_classpath_file_tmp, raw_target_classpath_file)
    updated = True

  # Make our actual classpath be symlinks, so that the paths are uniform across systems.
  # Note that we must do this even if we read the raw_target_classpath_file from the artifact
  # cache. If we cache the target_classpath_file we won't know how to create the symlinks.
  symlink_map = IvyUtils.symlink_cachepath(context.ivy_home, raw_target_classpath_file,
                                           symlink_dir, target_classpath_file)
  with _SYMLINK_MAP_LOCK:
    all_symlinks_map = context.products.get_data('symlink_map') or defaultdict(list)
    for path, symlink in symlink_map.items():
      all_symlinks_map[os.path.realpath(path)].append(symlink)
    context.products.safe_create_data('symlink_map', lambda: all_symlinks_map)

  with IvyUtils.cachepath(target_classpath_file) as classpath:
    stripped_classpath = [path.strip() for path in classpath]
    filtered_classpath = [path for path in stripped_classpath
                          if IvyUtils.is_classpath_artifact(path)]
    return ResolveResult(classpath=filtered_classpath,
                         raw_classpath_file=raw_target_classpath_file,
                         updated=updated)


class IvyTaskMixin(object):
  def ivy_resolve(self,
                  targets,
                  executor=None,
                  symlink_ivyxml=False,
                  silent=False,
                  workunit_name=None,
                  workunit_labels=None):

    if executor and not isinstance(executor, Executor):
      raise ValueError('The executor must be an Executor instance, given %s of type %s'
                       % (executor, type(executor)))

    ivy = Bootstrapper.default_ivy(java_executor=executor,
                                   bootstrap_workunit_factory=self.context.new_workunit)

    with self.invalidated(targets,
                          invalidate_dependents=True,
                          silent=silent) as invalidation_check:

      global_vts = VersionedTargetSet.from_versioned_targets(invalidation_check.all_vts)
      target_workdir = os.path.join(_ivy_workdir(self.context), global_vts.cache_key.hash)

      result = _resolve(self.context,
                        target_workdir,
                        targets,
                        ivy=ivy,
                        symlink_ivyxml=symlink_ivyxml,
                        workunit_name=workunit_name,
                        workunit_labels=workunit_labels)

      if result.updated and self.artifact_cache_writes_enabled():
        self.update_artifact_cache([(global_vts, [result.raw_classpath_file])])

      return result.classpath
