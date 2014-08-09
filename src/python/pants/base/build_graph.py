# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import logging
from collections import defaultdict

from twitter.common.collections import OrderedDict
from twitter.common.collections import OrderedSet

from pants.base.address import SyntheticAddress


logger = logging.getLogger(__name__)


class BuildGraph(object):
  """A directed acyclic graph of Targets and dependencies.
  Not necessarily connected.  Always serializable.
  """

  def __init__(self, run_tracker=None):
    self.run_tracker = run_tracker
    self.reset()

  def reset(self):
    self._target_by_address = OrderedDict()
    self._target_dependencies_by_address = defaultdict(set)
    self._target_dependees_by_address = defaultdict(set)
    self._derived_from_by_derivative_address = {}
    self._derivative_by_derived_from_address = defaultdict(set)

  def contains_address(self, address):
    return address in self._target_by_address

  def get_target_from_spec(self, spec):
    return self.get_target(SyntheticAddress.parse(spec))

  def get_target(self, address):
    return self._target_by_address.get(address, None)

  def dependencies_of(self, address):
    assert address in self._target_by_address, (
      'Cannot retrieve dependencies of {address} because it is not in the BuildGraph.'
      .format(address=address)
    )
    return self._target_dependencies_by_address[address]

  def dependents_of(self, address):
    assert address in self._target_by_address, (
      'Cannot retrieve dependents of {address} because it is not in the BuildGraph.'
      .format(address=address)
    )
    return self._target_dependees_by_address[address]

  def get_derived_from(self, address):
    """Get the target the specified target was derived from.

    If a Target was injected programmatically, e.g. from codegen, this allows us to trace its
    ancestry.  If a Target is not derived, default to returning itself.
    """
    parent_address = self._derived_from_by_derivative_address.get(address, address)
    return self.get_target(parent_address)

  def get_concrete_derived_from(self, address):
    """Get the concrete target the specified target was (directly or indirectly) derived from.

    The returned target is guaranteed to not have been derived from any other target.
    """
    current_address = address
    next_address = self._derived_from_by_derivative_address.get(current_address, current_address)
    while next_address != current_address:
      current_address = next_address
      next_address = self._derived_from_by_derivative_address.get(current_address, current_address)
    return self.get_target(current_address)

  def inject_target(self, target, dependencies=None, derived_from=None):
    dependencies = dependencies or frozenset()
    address = target.address

    if address in self._target_by_address:
      raise ValueError('A Target {existing_target} already exists in the BuildGraph at address'
                       ' {address}.  Failed to insert {target}.'
                       .format(existing_target=self._target_by_address[address],
                               address=address,
                               target=target))

    if derived_from:
      if not self.contains_address(derived_from.address):
        raise ValueError('Attempted to inject synthetic {target} derived from {derived_from}'
                         ' into the BuildGraph, but {derived_from} was not in the BuildGraph.'
                         ' Synthetic Targets must be derived from no Target (None) or from a'
                         ' Target already in the BuildGraph.'
                         .format(target=target,
                                 derived_from=derived_from))
      self._derived_from_by_derivative_address[target.address] = derived_from.address
      self._derivative_by_derived_from_address[derived_from.address].add(target.address)

    self._target_by_address[address] = target

    for dependency_address in dependencies:
      self.inject_dependency(dependent=address, dependency=dependency_address)

  def inject_dependency(self, dependent, dependency):
    if dependent not in self._target_by_address:
      raise ValueError('Cannot inject dependency from {dependent} on {dependency} because the'
                       ' dependent is not in the BuildGraph.'
                       .format(dependent=dependent, dependency=dependency))

    # TODO(pl): Unfortunately this is an unhelpful time to error due to a cycle.  Instead, we warn
    # and allow the cycle to appear.  It is the caller's responsibility to call sort_targets on the
    # entire graph to generate a friendlier CycleException that actually prints the cycle.
    # Alternatively, we could call sort_targets after every inject_dependency/inject_target, but
    # that could have nasty performance implications.  Alternative 2 would be to have an internal
    # data structure of the topologically sorted graph which would have acceptable amortized
    # performance for inserting new nodes, and also cycle detection on each insert.

    if dependency not in self._target_by_address:
      logger.warning('Injecting dependency from {dependent} on {dependency}, but the dependency'
                     ' is not in the BuildGraph.  This probably indicates a dependency cycle, but'
                     ' it is not an error until sort_targets is called on a subgraph containing'
                     ' the cycle.'
                     .format(dependent=dependent, dependency=dependency))

    if dependency in self.dependencies_of(dependent):
      logger.warn('{dependent} already depends on {dependency}'
                  .format(dependent=dependent, dependency=dependency))
    else:
      self._target_dependencies_by_address[dependent].add(dependency)
      self._target_dependees_by_address[dependency].add(dependent)

  def targets(self, predicate=None):
    """Returns all the targets in the graph in no particular order.

    :param predicate: A target predicate that will be used to filter the targets returned.
    """
    return filter(predicate, self._target_by_address.values())

  def sorted_targets(self):
    return sort_targets(self._target_by_address.values())

  def walk_transitive_dependency_graph(self, addresses, work, predicate=None):
    walked = set()
    def _walk_rec(address):
      if address not in walked:
        walked.add(address)
        target = self._target_by_address[address]
        if not predicate or predicate(target):
          work(target)
          for dep_address in self._target_dependencies_by_address[address]:
            _walk_rec(dep_address)
    for address in addresses:
      _walk_rec(address)

  def walk_transitive_dependee_graph(self, addresses, work, predicate=None):
    walked = set()
    def _walk_rec(address):
      if address not in walked:
        walked.add(address)
        target = self._target_by_address[address]
        if not predicate or predicate(target):
          work(target)
          for dep_address in self._target_dependees_by_address[address]:
            _walk_rec(dep_address)
    for address in addresses:
      _walk_rec(address)

  def transitive_dependees_of_addresses(self, addresses, predicate=None):
    ret = set()
    self.walk_transitive_dependee_graph(addresses, ret.add, predicate=predicate)
    return ret

  def transitive_subgraph_of_addresses(self, addresses, predicate=None):
    ret = set()
    self.walk_transitive_dependency_graph(addresses, ret.add, predicate=predicate)
    return ret

  def inject_synthetic_target(self,
                              address,
                              target_type,
                              dependencies=None,
                              derived_from=None,
                              **kwargs):
    if self.contains_address(address):
      raise ValueError('Attempted to inject synthetic {target_type} derived from {derived_from}'
                       ' into the BuildGraph with address {address}, but there is already a Target'
                       ' {existing_target} with that address'
                       .format(target_type=target_type,
                               derived_from=derived_from,
                               address=address,
                               existing_target=self.get_target(address)))

    target = target_type(name=address.target_name,
                         address=address,
                         build_graph=self,
                         **kwargs)
    self.inject_target(target, dependencies=dependencies, derived_from=derived_from)


class CycleException(Exception):
  """Thrown when a circular dependency is detected."""
  def __init__(self, cycle):
    Exception.__init__(self, 'Cycle detected:\n\t%s' % (
        ' ->\n\t'.join(target.address.spec for target in cycle)
    ))


def sort_targets(targets):
  """Returns the targets that targets depend on sorted from most dependent to least."""
  roots = OrderedSet()
  inverted_deps = defaultdict(OrderedSet)  # target -> dependent targets
  visited = set()
  path = OrderedSet()

  def invert(target):
    if target in path:
      path_list = list(path)
      cycle_head = path_list.index(target)
      cycle = path_list[cycle_head:] + [target]
      raise CycleException(cycle)
    path.add(target)
    if target not in visited:
      visited.add(target)
      for dependency in target.dependencies:
        inverted_deps[dependency].add(target)
        invert(dependency)
      else:
        roots.add(target)
    path.remove(target)

  for target in targets:
    invert(target)

  ordered = []
  visited.clear()

  def topological_sort(target):
    if target not in visited:
      visited.add(target)
      if target in inverted_deps:
        for dep in inverted_deps[target]:
          topological_sort(dep)
      ordered.append(target)

  for root in roots:
    topological_sort(root)

  return ordered
