# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from abc import abstractmethod
from collections import OrderedDict, defaultdict, deque

from twitter.common.collections import OrderedSet

from pants.build_graph.address import Address
from pants.build_graph.address_lookup_error import AddressLookupError
from pants.build_graph.target import Target
from pants.util.meta import AbstractClass


class BuildGraph(AbstractClass):
  """A directed acyclic graph of Targets and dependencies. Not necessarily connected.

  :API: public
  """

  class DuplicateAddressError(AddressLookupError):
    """The same address appears multiple times in a dependency list

    :API: public
    """

  class TransitiveLookupError(AddressLookupError):
    """Used to append the current node to the error message from an AddressLookupError

    :API: public
    """

  class ManualSyntheticTargetError(AddressLookupError):
    """Used to indicate that an synthetic target was defined manually

    :API: public
    """

  class DepthAgnosticWalk(object):
    """This is a utility class to aid in graph traversals that don't care about the depth."""

    def __init__(self):
      self._worked = set()
      self._expanded = set()

    def do_work_once(self, vertex):
      """Returns True exactly once for the given vertex."""
      if vertex in self._worked:
        return False
      self._worked.add(vertex)
      return True

    def expand_once(self, vertex, _):
      """Returns True exactly once for the given vertex."""
      if vertex in self._expanded:
        return False
      self._expanded.add(vertex)
      return True

  class DepthAwareWalk(DepthAgnosticWalk):
    """This is a utility class to aid in graph traversals that care about the depth."""

    def __init__(self):
      super(BuildGraph.DepthAwareWalk, self).__init__()
      self._expanded = defaultdict(set)

    def expand_once(self, vertex, level):
      """Returns True if this (vertex, level) pair has never been expanded, and False otherwise.

      This method marks the (vertex, level) pair as expanded after executing, such that this method
      will return True for a given (vertex, level) pair exactly once.
      """
      if level in self._expanded[vertex]:
        return False
      self._expanded[vertex].add(level)
      return True

  @staticmethod
  def closure(*vargs, **kwargs):
    """See `Target.closure_for_targets` for arguments.

    :API: public
    """
    return Target.closure_for_targets(*vargs, **kwargs)

  def __init__(self):
    self.reset()

  def reset(self):
    """Clear out the state of the BuildGraph, in particular Target mappings and dependencies.

    :API: public
    """
    self._target_by_address = OrderedDict()
    self._target_dependencies_by_address = defaultdict(OrderedSet)
    self._target_dependees_by_address = defaultdict(set)

  def contains_address(self, address):
    """
    :API: public
    """
    return address in self._target_by_address

  def get_target_from_spec(self, spec, relative_to=''):
    """Converts `spec` into an address and returns the result of `get_target`

    :API: public
    """
    return self.get_target(Address.parse(spec, relative_to=relative_to))

  def get_target(self, address):
    """Returns the Target at `address` if it has been injected into the BuildGraph, otherwise None.

    :API: public
    """
    return self._target_by_address.get(address, None)

  def dependencies_of(self, address):
    """Returns the dependencies of the Target at `address`.

    This method asserts that the address given is actually in the BuildGraph.

    :API: public
    """
    assert address in self._target_by_address, (
      'Cannot retrieve dependencies of {address} because it is not in the BuildGraph.'
      .format(address=address)
    )
    return self._target_dependencies_by_address[address]

  def dependents_of(self, address):
    """Returns the Targets which depend on the target at `address`.

    This method asserts that the address given is actually in the BuildGraph.

    :API: public
    """
    assert address in self._target_by_address, (
      'Cannot retrieve dependents of {address} because it is not in the BuildGraph.'
      .format(address=address)
    )
    return self._target_dependees_by_address[address]

  @abstractmethod
  def get_derived_from(self, address):
    """Get the target the specified target was derived from.

    If a Target was injected programmatically, e.g. from codegen, this allows us to trace its
    ancestry.  If a Target is not derived, default to returning itself.

    :API: public
    """

  @abstractmethod
  def get_concrete_derived_from(self, address):
    """Get the concrete target the specified target was (directly or indirectly) derived from.

    The returned target is guaranteed to not have been derived from any other target.

    :API: public
    """

  @abstractmethod
  def inject_target(self, target, dependencies=None, derived_from=None, synthetic=False):
    """Injects a fully realized Target into the BuildGraph.

    :API: public

    :param Target target: The Target to inject.
    :param list<Address> dependencies: The Target addresses that `target` depends on.
    :param Target derived_from: The Target that `target` was derived from, usually as a result
      of codegen.
    :param bool synthetic: Whether to flag this target as synthetic, even if it isn't derived
      from another target.
    """

  @abstractmethod
  def inject_dependency(self, dependent, dependency):
    """Injects a dependency from `dependent` onto `dependency`.

    It is an error to inject a dependency if the dependent doesn't already exist, but the reverse
    is not an error.

    :API: public

    :param Address dependent: The (already injected) address of a Target to which `dependency`
      is being added.
    :param Address dependency: The dependency to be injected.
    """

  def targets(self, predicate=None):
    """Returns all the targets in the graph in no particular order.

    :API: public

    :param predicate: A target predicate that will be used to filter the targets returned.
    """
    return filter(predicate, self._target_by_address.values())

  def sorted_targets(self):
    """
    :API: public

    :return: targets ordered from most dependent to least.
    """
    return sort_targets(self.targets())

  def walk_transitive_dependency_graph(self, addresses, work, predicate=None, postorder=False,
                                       leveled_predicate=None):
    """Given a work function, walks the transitive dependency closure of `addresses` using DFS.

    :API: public

    :param list<Address> addresses: The closure of `addresses` will be walked.
    :param function work: The function that will be called on every target in the closure using
      the specified traversal order.
    :param bool postorder: When ``True``, the traversal order is postorder (children before
      parents), else it is preorder (parents before children).
    :param function predicate: If this parameter is not given, no Targets will be filtered
      out of the closure.  If it is given, any Target which fails the predicate will not be
      walked, nor will its dependencies.  Thus predicate effectively trims out any subgraph
      that would only be reachable through Targets that fail the predicate.
    :param function leveled_predicate: Behaves identically to predicate, but takes the depth of the
      target in the search tree as a second parameter, and it is checked just before a dependency is
      expanded.
    """
    # Use the DepthAgnosticWalk if we can, because DepthAwareWalk does a bit of extra work that can
    # slow things down by few millis.
    walker = self.DepthAwareWalk if leveled_predicate else self.DepthAgnosticWalk
    walk = walker()
    def _walk_rec(addr, level=0):
      if not walk.expand_once(addr, level):
        return
      target = self._target_by_address[addr]
      if predicate and not predicate(target):
        return
      if not postorder and walk.do_work_once(target):
        work(target)
      for dep_address in self._target_dependencies_by_address[addr]:
        if not leveled_predicate \
                or leveled_predicate(self._target_by_address[dep_address], level):
          _walk_rec(dep_address, level + 1)
      if postorder and walk.do_work_once(target):
        work(target)
    for address in addresses:
      _walk_rec(address)

  def walk_transitive_dependee_graph(self, addresses, work, predicate=None, postorder=False):
    """Identical to `walk_transitive_dependency_graph`, but walks dependees preorder (or postorder
    if the postorder parameter is True).

    This is identical to reversing the direction of every arrow in the DAG, then calling
    `walk_transitive_dependency_graph`.

    :API: public
    """
    walked = set()

    def _walk_rec(addr):
      if addr not in walked:
        walked.add(addr)
        target = self._target_by_address[addr]
        if not predicate or predicate(target):
          if not postorder:
            work(target)
          for dep_address in self._target_dependees_by_address[addr]:
            _walk_rec(dep_address)
          if postorder:
            work(target)
    for address in addresses:
      _walk_rec(address)

  def transitive_dependees_of_addresses(self, addresses, predicate=None, postorder=False):
    """Returns all transitive dependees of `address`.

    Note that this uses `walk_transitive_dependee_graph` and the predicate is passed through,
    hence it trims graphs rather than just filtering out Targets that do not match the predicate.
    See `walk_transitive_dependee_graph for more detail on `predicate`.

    :API: public

    :param list<Address> addresses: The root addresses to transitively close over.
    :param function predicate: The predicate passed through to `walk_transitive_dependee_graph`.
    """
    ret = OrderedSet()
    self.walk_transitive_dependee_graph(addresses, ret.add, predicate=predicate,
                                        postorder=postorder)
    return ret

  def transitive_subgraph_of_addresses(self, addresses, *vargs, **kwargs):
    """Returns all transitive dependencies of `address`.

    Note that this uses `walk_transitive_dependencies_graph` and the predicate is passed through,
    hence it trims graphs rather than just filtering out Targets that do not match the predicate.
    See `walk_transitive_dependencies_graph for more detail on `predicate`.

    :API: public

    :param list<Address> addresses: The root addresses to transitively close over.
    :param function predicate: The predicate passed through to
      `walk_transitive_dependencies_graph`.
    :param bool postorder: When ``True``, the traversal order is postorder (children before
      parents), else it is preorder (parents before children).
    :param function predicate: If this parameter is not given, no Targets will be filtered
      out of the closure.  If it is given, any Target which fails the predicate will not be
      walked, nor will its dependencies.  Thus predicate effectively trims out any subgraph
      that would only be reachable through Targets that fail the predicate.
    :param function leveled_predicate: Behaves identically to predicate, but takes the depth of the
      target in the search tree as a second parameter, and it is checked just before a dependency is
      expanded.
    """
    ret = OrderedSet()
    self.walk_transitive_dependency_graph(addresses, ret.add,
                                          *vargs,
                                          **kwargs)
    return ret

  def transitive_subgraph_of_addresses_bfs(self, addresses, predicate=None, leveled_predicate=None):
    """Returns the transitive dependency closure of `addresses` using BFS.

    :API: public

    :param list<Address> addresses: The closure of `addresses` will be walked.
    :param function predicate: If this parameter is not given, no Targets will be filtered
      out of the closure.  If it is given, any Target which fails the predicate will not be
      walked, nor will its dependencies.  Thus predicate effectively trims out any subgraph
      that would only be reachable through Targets that fail the predicate.
    :param function leveled_predicate: Behaves identically to predicate, but takes the depth of the
      target in the search tree as a second parameter, and it is checked just before a dependency is
      expanded.
    """
    ordered_closure = OrderedSet()
    # Use the DepthAgnosticWalk if we can, because DepthAwareWalk does a bit of extra work that can
    # slow things down by few millis.
    walker = self.DepthAwareWalk if leveled_predicate else self.DepthAgnosticWalk
    walk = walker()
    to_walk = deque((0, addr) for addr in addresses)
    while len(to_walk) > 0:
      level, address = to_walk.popleft()
      target = self._target_by_address[address]
      if not walk.expand_once(target, level):
        continue
      if predicate and not predicate(target):
        continue
      if walk.do_work_once(target):
        ordered_closure.add(target)
      for addr in self._target_dependencies_by_address[address]:
        if not leveled_predicate or leveled_predicate(self._target_by_address[addr], level):
          to_walk.append((level + 1, addr))
    return ordered_closure

  @abstractmethod
  def inject_synthetic_target(self,
                              address,
                              target_type,
                              dependencies=None,
                              derived_from=None,
                              **kwargs):
    """Constructs and injects Target at `address` with optional `dependencies` and `derived_from`.

    This method is useful especially for codegen, where a "derived" Target is injected
    programmatically rather than read in from a BUILD file.

    :API: public

    :param Address address: The address of the new Target.  Must not already be in the BuildGraph.
    :param type target_type: The class of the Target to be constructed.
    :param list<Address> dependencies: The dependencies of this Target, usually inferred or copied
      from the `derived_from`.
    :param Target derived_from: The Target this Target will derive from.
    """

  @abstractmethod
  def inject_address_closure(self, address):
    """Resolves, constructs and injects a Target and its transitive closure of dependencies.

    This method is idempotent and will short circuit for already injected addresses. For all other
    addresses though, it delegates to an internal AddressMapper to resolve item the address points
    to.

    :API: public

    :param Address address: The address to inject.  Must be resolvable by `self._address_mapper` or
                            else be the address of an already injected entity.
    """

  @abstractmethod
  def inject_specs_closure(self, specs, fail_fast=None):
    """Resolves, constructs and injects Targets and their transitive closures of dependencies.

    :API: public

    :param specs: A list of base.specs.Spec objects to resolve and inject.
    :param fail_fast: Whether to fail quickly for the first error, or to complete all
      possible injections before failing.
    :returns: Yields a sequence of resolved Address objects.
    """

  def resolve(self, spec):
    """Returns an iterator over the target(s) the given address points to."""
    address = Address.parse(spec)
    # NB: This is an idempotent, short-circuiting call.
    self.inject_address_closure(address)
    return self.transitive_subgraph_of_addresses([address])


class CycleException(Exception):
  """Thrown when a circular dependency is detected.

  :API: public
  """

  def __init__(self, cycle):
    super(CycleException, self).__init__('Cycle detected:\n\t{}'.format(
        ' ->\n\t'.join(target.address.spec for target in cycle)
    ))


def invert_dependencies(targets):
  """
  :API: public

  :return: the full graph of dependencies for `targets` and the list of roots.
  """
  roots = set()
  inverted_deps = defaultdict(OrderedSet)  # target -> dependent targets
  visited = set()
  path = OrderedSet()

  def invert(tgt):
    if tgt in path:
      path_list = list(path)
      cycle_head = path_list.index(tgt)
      cycle = path_list[cycle_head:] + [tgt]
      raise CycleException(cycle)
    path.add(tgt)
    if tgt not in visited:
      visited.add(tgt)
      if tgt.dependencies:
        for dependency in tgt.dependencies:
          inverted_deps[dependency].add(tgt)
          invert(dependency)
      else:
        roots.add(tgt)

    path.remove(tgt)

  for target in targets:
    invert(target)

  return roots, inverted_deps


def sort_targets(targets):
  """
  :API: public

  :return: the targets that `targets` depend on sorted from most dependent to least.
  """

  roots, inverted_deps = invert_dependencies(targets)
  ordered = []
  visited = set()

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
