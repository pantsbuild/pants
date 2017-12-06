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
from pants.backend.python.tasks2.pex_build_util import (dump_python_distributions,
                                                        dump_requirements, dump_sources,
                                                        has_python_requirements, has_python_sources,
                                                        has_resources, is_local_python_dist)
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
    return ['python_dists']

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
        
        for vt in invalidation_check.all_vts:
          pex_path = os.path.join(vt.results_dir, '{}.pex'.format(vt.target.name))
          if not vt.valid:
            self.context.log.debug('cache for {} is invalid, rebuilding'.format(vt.target))
            built_dists.add(self._create_dist(vt.target)). # vt.results dir
          else:
            self.context.log.debug('using cache for {}'.format(vt.target))

    self.context.products.register_data('python_dists', built_dists)

  def _create_dist(self, dist_tgt):
    """Create a .whl file for the specified python_distribution target."""
    interpreter = self.context.products.get_data(PythonInterpreter)
    
    whl_location = ''
    # build whl from python_dist target
    whl = build_python_distribution(dist_tgt, interpreter, self.workdir, self.context.log)
    if whl:
      whl_location = whl
  
    return whl_location
