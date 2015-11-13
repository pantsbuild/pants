# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from collections import defaultdict

from twitter.common.util import topological_sort

from pants.backend.core.tasks.console_task import ConsoleTask
from pants.build_graph.target import Target


class SortTargets(ConsoleTask):
  @staticmethod
  def _is_target(item):
    return isinstance(item, Target)

  @classmethod
  def register_options(cls, register):
    super(SortTargets, cls).register_options(register)
    register('--reverse', action='store_true', default=False,
             help='Sort least-dependent to most-dependent.')

  def __init__(self, *args, **kwargs):
    super(SortTargets, self).__init__(*args, **kwargs)
    self._reverse = self.get_options().reverse

  def console_output(self, targets):
    depmap = defaultdict(set)

    def map_deps(target):
      deps = depmap[target.address.spec]
      for dep in target.dependencies:
        deps.add(dep.address.spec)

    for root in self.context.target_roots:
      root.walk(map_deps)

    tsorted = []
    for group in topological_sort(depmap):
      tsorted.extend(group)
    if self._reverse:
      tsorted = reversed(tsorted)

    roots = set(root.address.spec for root in self.context.target_roots)
    for address in tsorted:
      if address in roots:
        yield address
