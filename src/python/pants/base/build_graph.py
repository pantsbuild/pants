# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from collections import defaultdict
import logging
import traceback

from twitter.common.collections import OrderedDict, OrderedSet

from pants.base.address import SyntheticAddress


logger = logging.getLogger(__name__)


class BuildGraph(object):
  """A directed acyclic graph of Targets and dependencies. Not necessarily connected.
  """

  def __init__(self, address_mapper, run_tracker=None):
    self._address_mapper = address_mapper
    self.run_tracker = run_tracker
    self.reset()

  def reset(self):
    """Clear out the state of the BuildGraph, in particular Target mappings and dependencies."""
    self._addresses_already_closed = set()
    self._target_by_address = OrderedDict()
    self._target_dependencies_by_address = defaultdict(set)
    self._target_dependees_by_address = defaultdict(set)
    self._derived_from_by_derivative_address = {}
    self._derivative_by_derived_from_address = defaultdict(set)

  def contains_address(self, address):
    return address in self._target_by_address

  def get_target_from_spec(self, spec, relative_to=''):
    """Converts `spec` into a SyntheticAddress and returns the result of `get_target`"""
    return self.get_target(SyntheticAddress.parse(spec, relative_to=relative_to))

  def get_target(self, address):
    """Returns the Target at `address` if it has been injected into the BuildGraph, otherwise None.
    """
    return self._target_by_address.get(address, None)

  def dependencies_of(self, address):
    """Returns the dependencies of the Target at `address`.

    This method asserts that the address given is actually in the BuildGraph.
    """
    assert address in self._target_by_address, (
      'Cannot retrieve dependencies of {address} because it is not in the BuildGraph.'
      .format(address=address)
    )
    return self._target_dependencies_by_address[address]

  def dependents_of(self, address):
    """Returns the Targets which depend on the target at `address`.

    This method asserts that the address given is actually in the BuildGraph.
    """
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
    """Injects a fully realized Target into the BuildGraph.

    :param Target target: The Target to inject.
    :param list<Address> dependencies: The Target addresses that `target` depends on.
    :param Target derived_from: The Target that `target` was derived from, usually as a result
      of codegen.
    """

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
    """Injects a dependency from `dependent` onto `dependency`.

    It is an error to inject a dependency if the dependent doesn't already exist, but the reverse
    is not an error.

    :param Address dependent: The (already injected) address of a Target to which `dependency`
      is being added.
    :param Address dependency: The dependency to be injected.
    """
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
    """Given a work function, walks the transitive dependency closure of `addresses`.

    :param list<Address> addresses: The closure of `addresses` will be walked.
    :param function work: The function that will be called on every target in the closure.
    :param function predicate: If this parameter is not given, no Targets will be filtered
      out of the closure.  If it is given, any Target which fails the predicate will not be
      walked, nor will its dependencies.  Thus predicate effectively trims out any subgraph
      that would only be reachable through Targets that fail the predicate.
    """
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
    """Identical to `walk_transitive_dependency_graph`, but walks dependees.

    This is identical to reversing the direction of every arrow in the DAG, then calling
    `walk_transitive_dependency_graph`.
    """
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
    """Returns all transitive dependees of `address`.

    Note that this uses `walk_transitive_dependee_graph` and the predicate is passed through,
    hence it trims graphs rather than just filtering out Targets that do not match the predicate.
    See `walk_transitive_dependee_graph for more detail on `predicate`.

    :param list<Address> addresses: The root addresses to transitively close over.
    :param function predicate: The predicate passed through to `walk_transitive_dependee_graph`.
    """
    ret = set()
    self.walk_transitive_dependee_graph(addresses, ret.add, predicate=predicate)
    return ret

  def transitive_subgraph_of_addresses(self, addresses, predicate=None):
    """Returns all transitive dependencies of `address`.

    Note that this uses `walk_transitive_dependencies_graph` and the predicate is passed through,
    hence it trims graphs rather than just filtering out Targets that do not match the predicate.
    See `walk_transitive_dependencies_graph for more detail on `predicate`.

    :param list<Address> addresses: The root addresses to transitively close over.
    :param function predicate: The predicate passed through to
      `walk_transitive_dependencies_graph`.
    """
    ret = set()
    self.walk_transitive_dependency_graph(addresses, ret.add, predicate=predicate)
    return ret

  def inject_synthetic_target(self,
                              address,
                              target_type,
                              dependencies=None,
                              derived_from=None,
                              **kwargs):
    """Constructs and injects Target at `address` with optional `dependencies` and `derived_from`.

    This method is useful especially for codegen, where a "derived" Target is injected
    programmatically rather than read in from a BUILD file.

    :param Address address: The address of the new Target.  Must not already be in the BuildGraph.
    :param type target_type: The class of the Target to be constructed.
    :param list<Address> dependencies: The dependencies of this Target, usually inferred or copied
      from the `derived_from`.
    :param Target derived_from: The Target this Target will derive from.
    """
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

  def inject_address(self, address):
    """Delegates to an internal AddressMapper to resolve, construct, and inject a Target.

    :param Address address: The address to inject.  Must be resolvable by `self._address_mapper`.
    """
    if not self.contains_address(address):
      target_addressable = self._address_mapper.resolve(address)
      target = self.target_addressable_to_target(address, target_addressable)
      self.inject_target(target)

  def inject_address_closure(self, address):
    """Recursively calls `inject_address` through the transitive closure of dependencies."""

    if address in self._addresses_already_closed:
      return

    mapper = self._address_mapper

    target_addressable = mapper.resolve(address)

    self._addresses_already_closed.add(address)
    dep_addresses = list(mapper.specs_to_addresses(target_addressable.dependency_specs,
                                                   relative_to=address.spec_path))
    for dep_address in dep_addresses:
      self.inject_address_closure(dep_address)

    if not self.contains_address(address):
      target = self.target_addressable_to_target(address, target_addressable)
      self.inject_target(target, dependencies=dep_addresses)
    else:
      target = self.get_target(address)

    for traversable_spec in target.traversable_dependency_specs:
      self.inject_spec_closure(spec=traversable_spec, relative_to=address.spec_path)
      traversable_spec_target = self.get_target_from_spec(traversable_spec,
                                                          relative_to=address.spec_path)
      if traversable_spec_target not in target.dependencies:
        self.inject_dependency(dependent=target.address,
                               dependency=traversable_spec_target.address)
        target.mark_transitive_invalidation_hash_dirty()

    for traversable_spec in target.traversable_specs:
      self.inject_spec_closure(spec=traversable_spec, relative_to=address.spec_path)
      target.mark_transitive_invalidation_hash_dirty()

  def inject_spec_closure(self, spec, relative_to=''):
    """Constructs a SyntheticAddress from `spec` and calls `inject_address_closure`.

    :param string spec: A Target spec
    :param string relative_to: The spec_path of the BUILD file this spec was read from.
    """
    address = self._address_mapper.spec_to_address(spec, relative_to=relative_to)
    self.inject_address_closure(address)

  def target_addressable_to_target(self, address, addressable):
    """Realizes a TargetAddressable into a Target at `address`.

    :param TargetAddressable addressable:
    :param Address address:
    """
    try:
      target = addressable.get_target_type()(build_graph=self,
                                             address=address,
                                             **addressable.kwargs)
      target.with_description(addressable.description)
      return target
    except Exception:
      traceback.print_exc()
      logger.exception('Failed to instantiate Target with type {target_type} with name "{name}"'
                       ' at address {address}'
                       .format(target_type=addressable.get_target_type(),
                               name=addressable.name,
                               address=address))
      raise


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
