# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pex.interpreter import PythonInterpreter
from pex.pex_builder import PEXBuilder
from pex.pex_info import PexInfo

from pants.backend.python.targets.python_binary import PythonBinary
from pants.backend.python.targets.python_distribution import PythonDistribution
from pants.backend.python.tasks2.pex_build_util import (build_python_distribution,
                                                        dump_requirements, dump_sources,
                                                        has_python_requirements, has_python_sources,
                                                        has_resources, is_local_python_dist)
from pants.backend.python.tasks2.setup_py import SetupPyRunner
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.build_graph.target_scopes import Scopes
from pants.task.task import Task
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_mkdir_for
from pants.util.fileutil import atomic_copy


class PythonCreateDistributions(Task):
  """Create python distributions (.whl) from python_dist targets."""

  @classmethod
  def product_types(cls):
    return ['python-dists']

  @classmethod
  def prepare(cls, options, round_manager):
    round_manager.require_data(PythonInterpreter)
    round_manager.require_data('python')  # For codegen.

  @staticmethod
  def is_distribution(target):
    return isinstance(target, PythonDistribution)

  def __init__(self, *args, **kwargs):
    super(PythonCreateDistributions, self).__init__(*args, **kwargs)
    self._distdir = self.get_options().pants_distdir

  def execute(self):
    dist_targets = self.context.targets(self.is_distribution)
    built_dists = set()
    
    if dist_targets:
      # Check for duplicate distribution names, since we write the pexes to <dist>/<name>.pex.
      names = {}
      for dist_target in dist_targets:
        name = dist_target.name
        if name in names:
          raise TaskError('Cannot build two dist_targets with the same name in a single invocation. '
                          '{} and {} both have the name {}.'.format(dist_target, names[name], name))
        names[name] = dist_target

      with self.invalidated(dist_targets, invalidate_dependents=True) as invalidation_check:
        import pdb;pdb.set_trace
        for vt in invalidation_check.all_vts:
          built_dists.add(self._create_dist(vt.target)) # vt.results dir

    self.context.products.register_data('python-dists', built_dists)

  def _create_dist(self, dist_tgt):
    """Create a .whl file for the specified python_distribution target."""
    interpreter = self.context.products.get_data(PythonInterpreter)
    
    whl_location = ''
    # build whl from python_dist target
    dist_target_dir = build_python_distribution(dist_tgt, interpreter, self.workdir, self.context.log)
    
    # build the whl from pex API using tempdir and get its location
    install_dir = os.path.join(dist_target_dir, 'dist')
    if not os.path.exists(install_dir):
      safe_mkdir(install_dir)
    setup_runner = SetupPyRunner(dist_target_dir, 'bdist_wheel', interpreter=interpreter, install_dir=install_dir)
    setup_runner.run()

    # return the location of the whl on disk (somewhere in pantsd or dist)
    dists = os.listdir(install_dir)
    if len(dists) == 0:
      raise TaskError('No distributions were produced by python_create_distribution task.')
    elif len(dists) > 1:
      raise TaskError('Ambiguous whls found: %s' % (' '.join(dists)))
    else:
      return os.path.join(self.install_tmp, dists[0])
