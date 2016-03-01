# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.build_graph.address_lookup_error import AddressLookupError
from pants.build_graph.build_graph import BuildGraph
from pants.engine.exp.legacy.parser import TargetAdaptor
from pants.engine.exp.nodes import Return, SelectNode, State, Throw
from pants.engine.exp.selectors import Select, SelectDependencies, SelectLiteral
from pants.util.objects import datatype


class ExpGraph(BuildGraph):
  """A directed acyclic graph of Targets and dependencies. Not necessarily connected.

  This implementation is backed by a Scheduler that is able to resolve LegacyBuildGraphNodes.
  """

  def __init__(self, scheduler, engine):
    """Construct a graph given an address_mapper and Scheduler.

    :param scheduler: A Scheduler that is configured to be able to resolve LegacyBuildGraphNodes.
    :param scheduler: An Engine subclass to execute calls to `inject`.
    """
    self._scheduler = scheduler
    self._graph = scheduler.product_graph
    self._engine = engine
    super(ExpGraph, self).__init__()

  def reset(self):
    super(ExpGraph, self).reset()
    self._index(self._graph.completed_nodes().keys())

  def _index(self, roots):
    """Index from the given roots into the storage provided by the base class.

    This is an additive operation: any existing connections involving these nodes are preserved.
    """
    addresses = set()
    # Index the ProductGraph.
    # TODO: It's not very common to actually use the dependencies of a Node during a walk... should
    # consider removing those from that API.
    for ((node, state), _) in self._graph.walk(roots=roots):
      # Locate nodes that contain LegacyBuildGraphNode values.
      if type(state) is Throw:
        # TODO: get access to `Subjects` instance in order to `to-str` more effectively here.
        raise AddressLookupError(
            'Build graph construction failed for {}:\n  {}'.format(node.subject_key, state.exc))
      elif type(state) is not Return:
        State.raise_unrecognized(state)
      if node.product is not LegacyBuildGraphNode:
        continue
      if type(node) is not SelectNode:
        continue

      # We have a successfully parsed a LegacyBuildGraphNode.
      target = state.value.target
      address = target.address
      addresses.add(address)
      self._target_by_address[address] = target
      dependencies = state.value.dependency_addresses
      self._target_dependencies_by_address[address] = dependencies
      for dependency in dependencies:
         self._target_dependees_by_address[dependency].add(address)
    return addresses

  @property
  def address_mapper(self):
    raise ValueError('Not implemented.')

  def get_derived_from(self, address):
    raise ValueError('Not implemented.')

  def get_concrete_derived_from(self, address):
    raise ValueError('Not implemented.')

  def inject_target(self, target, dependencies=None, derived_from=None, synthetic=False):
    raise ValueError('Not implemented.')

  def inject_dependency(self, dependent, dependency):
    raise ValueError('Not implemented.')

  def inject_synthetic_target(self,
                              address,
                              target_type,
                              dependencies=None,
                              derived_from=None,
                              **kwargs):
    raise ValueError('Not implemented.')

  def inject_address_closure(self, address):
    raise ValueError('Not implemented.')

  def inject_specs_closure(self, specs, fail_fast=None, spec_excludes=None):
    # Request loading of these specs.
    request = self._scheduler.execution_request(products=[LegacyBuildGraphNode], subjects=specs)
    result = self._engine.execute(request)
    if result.error:
      raise result.error
    # Update the base class indexes for this request.
    for address in self._index(request.roots):
      yield address


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
