# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.core.tasks.console_task import ConsoleTask


class MinimalCover(ConsoleTask):
  """Outputs a minimal covering set of targets.

  For a given set of input targets, the output targets transitive dependency set will include all
  the input targets without gaps.
  """

  def console_output(self, _):
    internal_deps = set()
    for target in self.context.target_roots:
      internal_deps.update(self._collect_internal_deps(target))

    minimal_cover = set()
    for target in self.context.target_roots:
      if target not in internal_deps and target not in minimal_cover:
        minimal_cover.add(target)
        yield target.address.spec

  def _collect_internal_deps(self, target):
    internal_deps = set()
    target.walk(internal_deps.add)
    internal_deps.discard(target)
    return internal_deps
