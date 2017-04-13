# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.build_graph.target import Target
from pants.task.console_task import ConsoleTask


class MinimalCover(ConsoleTask):
  """Print a minimal covering set of targets.

  For a given set of input targets, the output targets transitive dependency set will include all
  the input targets without gaps.
  """

  def console_output(self, _):
    internal_deps = self._collect_internal_deps(self.context.target_roots)

    minimal_cover = set()
    for target in self.context.target_roots:
      if target not in internal_deps and target not in minimal_cover:
        minimal_cover.add(target)
        yield target.address.spec

  def _collect_internal_deps(self, targets):
    """Collect one level of dependencies from the given targets, and then transitively walk.

    This is different from directly executing `Target.closure_for_targets`, because the
    resulting set will not include the roots unless the roots depend on one another.
    """
    roots = set()
    for target in targets:
      roots.update(target.dependencies)
    return Target.closure_for_targets(roots)
