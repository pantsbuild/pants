# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.build_graph.address_lookup_error import AddressLookupError
from pants.build_graph.build_graph import BuildGraph
from pants.engine.exp.legacy.parsers import LegacyPythonCallbacksParser, TargetAdaptor
from pants.engine.exp.selectors import Select, SelectDependencies, SelectLiteral
from pants.util.objects import datatype


class ExpGraph(BuildGraph):
  """A directed acyclic graph of Targets and dependencies. Not necessarily connected."""

  def __init__(self, address_mapper, product_graph):
    super(self, ExpGraph).__init__(address_mapper)
    self._graph = product_graph
    self._address_mapper = address_mapper
    self._reset_private()

  def _reset_private(self):
    # A dict indexing LegacyBuildGraphNode instances by Address.
    self._targets_by_address = {}
    self._target_dependencies_by_address = defaultdict(OrderedSet)
    self._target_dependees_by_address = defaultdict(set)

    # Index the ProductGraph.
    for node, state in self._graph.completed_nodes().items():
      # Locate nodes that contain LegacyBuildGraphNode values.
      if node.product is not LegacyBuildGraphNode:
        continue
      if type(node) is not SelectNode:
        continue
      if type(state) in [Throw, Noop]:
        # TODO: get access to `Subjects` instance in order to `to-str` more effectively here.
        raise AddressLookupError(
            'Build graph construction failed for {}: {}'.format(node.subject_key, state))
      elif type(state) is not Return:
        State.raise_unrecognized(state)

      # We have a successfully parsed LegacyBuildGraphNode.
      target = state.value.target
      address = target.address
      self._targets_by_address[address] = target
      dependencies = state.value.dependency_addresses
      self._target_dependencies_by_address[address] = dependencies
      for dependency in dependencies:
        self._target_dependees_by_address[dependency].add(address)

  def reset(self):
    self._reset_private()

  def contains_address(self, address):
    """
    :API: public
    """

  def get_target(self, address):
    """Returns the Target at `address` if it has been injected into the BuildGraph, otherwise None.

    :API: public
    """

  def dependencies_of(self, address):
    """Returns the dependencies of the Target at `address`.

    This method asserts that the address given is actually in the BuildGraph.

    :API: public
    """

  def dependents_of(self, address):
    """Returns the Targets which depend on the target at `address`.

    This method asserts that the address given is actually in the BuildGraph.

    :API: public
    """

  def get_derived_from(self, address):
    """Get the target the specified target was derived from.

    If a Target was injected programmatically, e.g. from codegen, this allows us to trace its
    ancestry.  If a Target is not derived, default to returning itself.

    :API: public
    """

  def get_concrete_derived_from(self, address):
    """Get the concrete target the specified target was (directly or indirectly) derived from.

    The returned target is guaranteed to not have been derived from any other target.

    :API: public
    """

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

  def walk_transitive_dependency_graph(self, addresses, work, predicate=None, postorder=False):
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
    """

  def walk_transitive_dependee_graph(self, addresses, work, predicate=None, postorder=False):
    """Identical to `walk_transitive_dependency_graph`, but walks dependees preorder (or postorder
    if the postorder parameter is True).

    This is identical to reversing the direction of every arrow in the DAG, then calling
    `walk_transitive_dependency_graph`.

    :API: public
    """

  def transitive_subgraph_of_addresses_bfs(self, addresses, predicate=None):
    """Returns the transitive dependency closure of `addresses` using BFS.

    :API: public

    :param list<Address> addresses: The closure of `addresses` will be walked.
    :param function predicate: If this parameter is not given, no Targets will be filtered
      out of the closure.  If it is given, any Target which fails the predicate will not be
      walked, nor will its dependencies.  Thus predicate effectively trims out any subgraph
      that would only be reachable through Targets that fail the predicate.
    """

  def inject_synthetic_target(self,
                              address,
                              target_type,
                              dependencies=None,
                              derived_from=None,
                              **kwargs):
    raise Exception('Not implemented.')

  def inject_address_closure(self, address):
    """Resolves, constructs and injects a Target and its transitive closure of dependencies.

    This method is idempotent and will short circuit for already injected addresses. For all other
    addresses though, it delegates to an internal AddressMapper to resolve item the address points
    to.

    :API: public

    :param Address address: The address to inject.  Must be resolvable by `self._address_mapper` or
                            else be the address of an already injected entity.
    """



class LegacyBuildGraphNode(datatype('LegacyGraphNode', ['target', 'dependency_addresses'])):
  """A Node to represent a node in the legacy BuildGraph.

  A facade implementing the legacy BuildGraph would inspect only these entries in the ProductGraph.
  """


def reify_legacy_graph(legacy_target, dependency_nodes):
  """Given a TargetAdaptor and LegacyBuildGraphNodes for its deps, return a LegacyBuildGraphNode."""
  # Instantiate the Target from the TargetAdaptor struct.
  target = legacy_target
  return LegacyBuildGraphNode(target, [node.target.address for node in dependency_nodes])


def create_legacy_graph_tasks():
  """Create tasks to recursively parse the legacy graph."""
  return [
      # Given a TargetAdaptor and its dependencies, construct a Target.
      (LegacyBuildGraphNode,
       [Select(TargetAdaptor),
        SelectDependencies(LegacyBuildGraphNode, TargetAdaptor)],
       reify_legacy_graph)
    ]
