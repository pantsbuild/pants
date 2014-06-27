# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from collections import defaultdict

from twitter.common.util import topological_sort

from pants.base.target import Target
from pants.backend.core.tasks.console_task import ConsoleTask


class SortTargets(ConsoleTask):
  @staticmethod
  def _is_target(item):
    return isinstance(item, Target)

  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    super(SortTargets, cls).setup_parser(option_group, args, mkflag)

    option_group.add_option(mkflag("reverse"), mkflag("reverse", negate=True),
                            dest="sort_targets_reverse", default=False,
                            action="callback", callback=mkflag.set_bool,
                            help="[%default] Sort least dependent to most.")

  def __init__(self, *args, **kwargs):
    super(SortTargets, self).__init__(*args, **kwargs)
    self._reverse = self.context.options.sort_targets_reverse

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
