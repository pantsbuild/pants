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
from pants.util.dirutil import safe_mkdir


class PythonCreateDistributions(Task):
  """Create python distributions (.whl) from python_dist targets."""

  options_scope = 'python-create-distributions'
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

    # Copy sources and setup.py over to vt results directory for packaging.
    # NB: The directory structure of the destination directory needs to match 1:1
    # with the directory structure that setup.py expects.
    for src_relative_to_target_base in dist_tgt.sources_relative_to_target_base():
      src_rel_to_results_dir = os.path.join(dist_target_dir, src_relative_to_target_base)
      safe_mkdir(os.path.dirname(src_rel_to_results_dir))
      abs_src_path = os.path.join(get_buildroot(),
                                  dist_tgt.address.spec_path,
                                  src_relative_to_target_base)
      shutil.copyfile(abs_src_path, src_rel_to_results_dir)
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
    else:
      return os.path.join(os.path.abspath(install_dir), dists[0])
