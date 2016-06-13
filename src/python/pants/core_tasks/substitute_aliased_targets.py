# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.build_graph.aliased_target import AliasTarget
from pants.task.task import Task


class SubstituteAliasedTargets(Task):
  """Substitutes AliasedTargets with their dependencies where applicable."""

  def execute(self):
    # Replace aliased_targets in target_roots with their dependencies. This permits doing things
    # like running jvm_binaries that you've referenced indirectly via an alias.
    self._substitute_target_roots()

    # TODO(gmalmquist): Make this work with deferred sources?

    # "Hotwire" every aliased_target's dependencies to the aliased_target's dependees. This provides
    # a mechanism to indirectly reference targets that have intransitive dependencies.
    for aliased_target in self.context.targets(lambda t: isinstance(t, AliasTarget)):
      self._inject_dependencies_into_dependees(aliased_target)

  def _substitute_target_roots(self):
    original_roots = list(self.context.target_roots)
    new_roots = []
    for target in original_roots:
      new_roots.extend(self._expand(target))
    self.context._replace_targets(new_roots)

  def _inject_dependencies_into_dependees(self, target):
    build_graph = self.context.build_graph
    for dependee in tuple(build_graph.dependents_of(target.address)):
      for dependency in target.dependencies:
        build_graph.inject_dependency(dependee, dependency.address)

  def _expand(self, target):
    self.context.log.debug('expanding {}'.format(target.address.spec))
    if isinstance(target, AliasTarget):
      for dep in target.dependencies:
        for expanded in self._expand(dep):
          yield expanded
    else:
      yield target
