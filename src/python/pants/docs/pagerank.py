# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from collections import defaultdict

from pants import is_concrete  # XXX This target doesn't exist
from pants.backend.core.tasks.console_task import ConsoleTask


class PageRank(ConsoleTask):
  """Measure how "depended-upon" the targets are."""

  def console_output(self, targets):
    dependencies_by_target = defaultdict(set)
    dependees_by_target = defaultdict(set)
    pagerank_by_target = defaultdict(lambda: 1.0)

    self._calc_deps(targets, dependencies_by_target, dependees_by_target)
    self._pagerank(dependees_by_target, dependencies_by_target, pagerank_by_target)
    return self._report(pagerank_by_target)

  def _calc_deps(self, targets, dependencies_by_target, dependees_by_target):
    for target in filter(lambda x: hasattr(x, "dependencies"), targets):
      if not dependencies_by_target.has_key(target):
        for dependency in target.dependencies:
          for resolved in dependency.resolve():
            if is_concrete(resolved):
              dependencies_by_target[target].add(resolved)

      for dependency in target.dependencies:
        for resolved in dependency.resolve():
          if is_concrete(resolved):
            dependees_by_target[resolved].add(target)

  def _pagerank(self, dependees_by_target, dependencies_by_target, pagerank_by_target):
    """Calculate PageRank."""
    d = 0.85
    for x in range(0, 100):
      for target, dependees in dependees_by_target.iteritems():
        contributions = map(
          lambda t: pagerank_by_target[t] / len(dependencies_by_target[t]), dependees)
        pagerank_by_target[target] = (1-d) + d * sum(contributions)

  def _report(self, pagerank_by_target):
    """Yield the report lines."""
    for target in sorted(pagerank_by_target, key=pagerank_by_target.get, reverse=True):
      yield '%f - %s' % (pagerank_by_target[target], target)
