# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import shutil

from pex.interpreter import PythonInterpreter

from pants.backend.python.targets.python_distribution import PythonDistribution
from pants.backend.python.tasks2.setup_py import SetupPyRunner
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.fingerprint_strategy import DefaultFingerprintStrategy
from pants.task.task import Task
from pants.util.dirutil import safe_mkdir, safe_mkdir_for


class PythonCreateDistributions(Task):
  """Create python distributions (.whl) from python_dist targets."""

  PYTHON_DISTS = 'user_defined_python_dists'

  @classmethod
  def product_types(cls):
    return [cls.PYTHON_DISTS]

  @classmethod
  def prepare(cls, options, round_manager):
    round_manager.require_data(PythonInterpreter)

  @staticmethod
  def is_distribution(target):
    return isinstance(target, PythonDistribution)

  @property
  def local_dists_workdir(self):
    return os.path.join(self.workdir, 'local_dists')

  @property
  def cache_target_dirs(self):
    return True

  def execute(self):
    dist_targets = self.context.targets(self.is_distribution)
    built_dists = set()
    
    if dist_targets:
      local_dists_workdir = self.local_dists_workdir
      if not os.path.exists(self.local_dists_workdir):
        safe_mkdir(local_dists_workdir)

      with self.invalidated(dist_targets,
                            fingerprint_strategy=DefaultFingerprintStrategy(),
                            invalidate_dependents=True) as invalidation_check:
        for vt in invalidation_check.all_vts:
          if vt.valid:
            built_dists.add(self._get_whl_from_dir(os.path.join(vt.results_dir, 'dist')))
          else:
            built_dists.add(self._create_dist(vt.target, vt.results_dir))

    self.context.products.register_data(self.PYTHON_DISTS, built_dists)

  def _create_dist(self, dist_tgt, dist_target_dir):
    """Create a .whl file for the specified python_distribution target."""
    
    interpreter = self.context.products.get_data(PythonInterpreter)
    safe_mkdir(dist_target_dir)

    # Copy sources and setup.py over for packaging.
    sources_rel_to_target_base = dist_tgt.sources_relative_to_target_base()
    sources_rel_to_buildroot = dist_tgt.sources_relative_to_buildroot()
    # NB: We need target paths both relative to the target base and relative to
    # the build root for the shutil file copying below.
    # TODO: simplify block
    sources = zip(sources_rel_to_buildroot, sources_rel_to_target_base)
    for source_relative_to_build_root, source_relative_to_target_base in sources:
      source_rel_to_dist_dir = os.path.join(dist_target_dir, source_relative_to_target_base)
      safe_mkdir(os.path.dirname(source_rel_to_dist_dir))
      shutil.copyfile(os.path.join(get_buildroot(), source_relative_to_build_root),
                      source_rel_to_dist_dir)


    #for source in dist_tgt.sources_relative_to_source_root():
     # dest_source = os.path.join(dist_target_dir, source)
      #safe_mkdir_for(dest_source)
      #shutil.copyfile(os.path.join(dist_tgt.target_base, source), dest_source)


    # Build the whl from pex API using tempdir and get its location.
    install_dir = os.path.join(dist_target_dir, 'dist')
    safe_mkdir(install_dir)
    setup_runner = SetupPyRunner(dist_target_dir, 'bdist_wheel', interpreter=interpreter, install_dir=install_dir)
    setup_runner.run()
    return self._get_whl_from_dir(install_dir)

  def _get_whl_from_dir(self, install_dir):
    """Return the location of the whl on disk."""
    dists = os.listdir(install_dir)
    if len(dists) == 0:
      raise TaskError('No distributions were produced by python_create_distribution task.')
    elif len(dists) > 1:
      raise TaskError('Ambiguous whls found: %s' % (' '.join(dists)))
    else:
      return os.path.join(os.path.abspath(install_dir), dists[0])
