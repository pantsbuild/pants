# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.task.console_task import ConsoleTask


class DepGraph(ConsoleTask):
  """Outputs a dot-format graph of transitive dependencies."""

  def console_output(self, targets):
    to_visit = set(targets)
    visited = set()

    edges = set()

    while to_visit:
      target = to_visit.pop()
      visited.add(target)
      for dep in target.dependencies:
        if dep not in visited:
          to_visit.add(dep)
        edges.add("  \"{}\" -> \"{}\";".format(target.address.reference(), dep.address.reference()))

    yield "digraph dependencies {"
    for edge in sorted(edges):
      yield edge
    yield "}"
