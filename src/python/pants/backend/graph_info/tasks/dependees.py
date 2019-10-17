# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
from collections import defaultdict

from pants.base.specs import DescendantAddresses
from pants.task.console_task import ConsoleTask
from pants.util.meta import classproperty


class ReverseDepmap(ConsoleTask):
  """List all targets that depend on any of the input targets."""

  @classmethod
  def register_options(cls, register):
    super().register_options(register)
    register('--closed', type=bool,
             help='Include the input targets in the output along with the dependees.')
    # TODO: consider refactoring out common output format methods into MultiFormatConsoleTask.
    register('--output-format', default='text', choices=['text', 'json'],
             help='Output format of results.')
    register('--transitive', type=bool, default=False,
             help='Whether to include only the first level of dependendees.')

  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)

    self._closed = self.get_options().closed

  def console_output(self, _):
    dependees_by_target = defaultdict(set)
    for address in self.context.build_graph.inject_specs_closure([DescendantAddresses('')]):
      target = self.context.build_graph.get_target(address)
      # TODO(John Sirois): tighten up the notion of targets written down in a BUILD by a
      # user vs. targets created by pants at runtime.
      concrete_target = self.get_concrete_target(target)
      for dependency in concrete_target.dependencies:
        dependency = self.get_concrete_target(dependency)
        dependees_by_target[dependency].add(concrete_target)

    roots = set(self.context.target_roots)
    if self.get_options().output_format == 'json':
      deps = defaultdict(list)
      for root in roots:
        if self._closed:
          deps[root.address.spec].append(root.address.spec)
        for dependent in self.get_dependents(dependees_by_target, [root]):
          deps[root.address.spec].append(dependent.address.spec)
      for address in deps.keys():
        deps[address].sort()
      yield json.dumps(deps, indent=4, separators=(',', ': '), sort_keys=True)
    else:
      if self._closed:
        # N.B. Sorting is necessary because `roots` is a set, and in Python 3 sets
        # are no longer consistently sorted (even though dictionaries are in 3.6+).
        # Without this sort, the output of `./pants dependees` will vary every run.
        for root in sorted(roots):
          yield root.address.spec

      # N.B. Sorting is necessary here for consistent output in Python 3. See above N.B.
      for dependent in sorted(self.get_dependents(dependees_by_target, roots)):
        yield dependent.address.spec

  def get_dependents(self, dependees_by_target, roots):
    check = set(roots)
    known_dependents = set()
    while True:
      dependents = set(known_dependents)
      for target in check:
        dependents.update(dependees_by_target[target])
      check = dependents - known_dependents
      if not check or not self.act_transitively:
        return dependents - set(roots)
      known_dependents = dependents

  def get_concrete_target(self, target):
    return target.concrete_derived_from
