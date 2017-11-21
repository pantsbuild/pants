# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)


class PythonDistributionCreate(Task):
  """Create a Python distribution containing .py and .c/.cpp sources"""

  @staticmethod
  def is_distribution(target):
    return isinstance(target, PythonDistribution)

  def __init__(self, *args, **kwargs):
    super(PythonDistributionCreate, self).__init__(*args, **kwargs)
    self._distdir = self.get_options().pants_distdir

  def execute(self):
    distributions = self.context.targets(self.is_distribution)

    # Check for duplicate distribution names, since we write the pexes to <dist>/<name>.pex.
    names = {}
    for distribution in distributions:
      name = distribution.name
      if name in names:
        raise TaskError('Cannot build two distributions with the same name in a single invocation. '
                        '{} and {} both have the name {}.'.format(distribution, names[name], name))
      names[name] = distribution

    with self.invalidated(distributions, invalidate_dependents=True) as invalidation_check:
      for vt in invalidation_check.all_vts:
        pex_path = os.path.join(vt.results_dir, '{}.pex'.format(vt.target.name))
        if not vt.valid:
          self.context.log.debug('cache for {} is invalid, rebuilding'.format(vt.target))
          self._create_distribution(vt.target, vt.results_dir)
        else:
          self.context.log.debug('using cache for {}'.format(vt.target))

  def _create_distribution(self, source_dir, results_dir, setup_file):
    """Create a .pex file containing an inline wheel for the specified folder and setup.py."""
    pass
