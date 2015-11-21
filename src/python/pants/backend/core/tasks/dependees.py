# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from collections import defaultdict

from pants.backend.core.tasks.target_filter_task_mixin import TargetFilterTaskMixin
from pants.base.build_environment import get_buildroot
from pants.task.console_task import ConsoleTask


class ReverseDepmap(TargetFilterTaskMixin, ConsoleTask):
  """Outputs all targets whose dependencies include at least one of the input targets."""

  @classmethod
  def register_options(cls, register):
    super(ReverseDepmap, cls).register_options(register)
    register('--transitive', default=False, action='store_true',
             help='List transitive dependees.')
    register('--closed', default=False, action='store_true',
             help='Include the input targets in the output along with the dependees.')

  def __init__(self, *args, **kwargs):
    super(ReverseDepmap, self).__init__(*args, **kwargs)

    self._transitive = self.get_options().transitive
    self._closed = self.get_options().closed
    self._spec_excludes = self.get_options().spec_excludes

  def console_output(self, _):
    address_mapper = self.context.address_mapper
    buildfiles = address_mapper.scan_buildfiles(get_buildroot(),
                                                spec_excludes=self._spec_excludes)

    build_graph = self.context.build_graph
    build_file_parser = self.context.build_file_parser

    dependees_by_target = defaultdict(set)
    for build_file in buildfiles:
      address_map = build_file_parser.parse_build_file(build_file)
      for address in address_map.keys():
        build_graph.inject_address_closure(address)
      for address in address_map.keys():
        target = build_graph.get_target(address)
        # TODO(John Sirois): tighten up the notion of targets written down in a BUILD by a
        # user vs. targets created by pants at runtime.
        target = self.get_concrete_target(target)
        for dependency in target.dependencies:
          dependency = self.get_concrete_target(dependency)
          dependees_by_target[dependency].add(target)

    roots = set(self.context.target_roots)
    if self._closed:
      for root in roots:
        yield root.address.spec

    for dependent in self.get_dependents(dependees_by_target, roots):
      yield dependent.address.spec

  def get_dependents(self, dependees_by_target, roots):
    check = set(roots)
    known_dependents = set()
    while True:
      dependents = set(known_dependents)
      for target in check:
        dependents.update(dependees_by_target[target])
      check = dependents - known_dependents
      if not check or not self._transitive:
        return dependents - set(roots)
      known_dependents = dependents

  def get_concrete_target(self, target):
    return target.concrete_derived_from
