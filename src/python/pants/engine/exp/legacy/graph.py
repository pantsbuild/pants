# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.base.exceptions import TargetDefinitionException
from pants.build_graph.address import Addresses
from pants.build_graph.address_lookup_error import AddressLookupError
from pants.build_graph.build_graph import BuildGraph
from pants.engine.exp.legacy.globs import BaseGlobs, Files
from pants.engine.exp.legacy.parser import TargetAdaptor
from pants.engine.exp.nodes import Return, SelectNode, State, Throw
from pants.engine.exp.selectors import Select, SelectDependencies
from pants.util.objects import datatype


class ExpGraph(BuildGraph):
  """A directed acyclic graph of Targets and dependencies. Not necessarily connected.

  This implementation is backed by a Scheduler that is able to resolve LegacyBuildGraphNodes.
  """

  def __init__(self, scheduler, engine, symbol_table_cls):
    """Construct a graph given a Scheduler, Engine, and a SymbolTable class.

    :param scheduler: A Scheduler that is configured to be able to resolve LegacyBuildGraphNodes.
    :param engine: An Engine subclass to execute calls to `inject`.
    :param symbol_table_cls: A SymbolTable class used to instantiate Target objects. Must match
      the symbol table installed in the scheduler (TODO: see comment in `_instantiate_target`).
    """
    self._scheduler = scheduler
    self._graph = scheduler.product_graph
    self._target_types = symbol_table_cls.aliases().target_types
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
        raise AddressLookupError(
            'Build graph construction failed for {}:\n  {}'.format(node.subject, state.exc))
      elif type(state) is not Return:
        State.raise_unrecognized(state)
      if node.product is not LegacyBuildGraphNode:
        continue
      if type(node) is not SelectNode:
        continue

      # We have a successfully parsed a LegacyBuildGraphNode.
      target_adaptor = state.value.target_adaptor
      address = target_adaptor.address
      addresses.add(address)
      if address not in self._target_by_address:
        self._target_by_address[address] = self._instantiate_target(target_adaptor)
      dependencies = state.value.dependency_addresses
      self._target_dependencies_by_address[address] = dependencies
      for dependency in dependencies:
        self._target_dependees_by_address[dependency].add(address)
    return addresses

  def _instantiate_sources(self, relpath, sources):
    """Converts captured `sources` arguments to what is expected by `Target.create_sources_field`.

    For a literal sources list or a BaseGlobs subclass, create a wrapping FilesetWithSpec.
    For an Addresses object, return as is.
    """
    if isinstance(sources, Addresses):
      return sources
    if not isinstance(sources, BaseGlobs):
      sources = Files(*sources)
    return sources.to_fileset_with_spec(self._engine, self._scheduler, relpath)

  def _instantiate_target(self, target_adaptor):
    """Given a TargetAdaptor struct previously parsed from a BUILD file, instantiate a Target.

    TODO: This assumes that the SymbolTable used for parsing matches the SymbolTable passed
    to this graph. Would be good to make that more explicit, but it might be better to nuke
    the Target subclassing pattern instead, and lean further into the "configuration composition"
    model explored in the `exp` package.
    """
    target_cls = self._target_types[target_adaptor.type_alias]
    try:
      # Pop dependencies, which was already consumed while constructing LegacyBuildGraphNode.
      kwargs = target_adaptor.kwargs()
      kwargs.pop('dependencies')
      # Replace the sources argument with a FilesetWithSpecs instance, or None.
      spec_path = kwargs.pop('spec_path')
      sources = kwargs.get('sources', None)
      if sources is not None:
        kwargs['sources'] = self._instantiate_sources(spec_path, sources)
      # Instantiate.
      return target_cls(build_graph=self, **kwargs)
    except TargetDefinitionException:
      raise
    except Exception as e:
      raise TargetDefinitionException(
          target_adaptor.address,
          'Failed to instantiate Target with type {}: {}'.format(target_cls, e))

  def get_derived_from(self, address):
    raise NotImplementedError('Not implemented.')

  def get_concrete_derived_from(self, address):
    raise NotImplementedError('Not implemented.')

  def inject_target(self, target, dependencies=None, derived_from=None, synthetic=False):
    raise NotImplementedError('Not implemented.')

  def inject_dependency(self, dependent, dependency):
    raise NotImplementedError('Not implemented.')

  def inject_synthetic_target(self,
                              address,
                              target_type,
                              dependencies=None,
                              derived_from=None,
                              **kwargs):
    raise NotImplementedError('Not implemented.')

  def inject_address_closure(self, address):
    raise NotImplementedError('Not implemented.')

  def inject_specs_closure(self, specs, fail_fast=None):
    # Request loading of these specs.
    request = self._scheduler.execution_request([LegacyBuildGraphNode], specs)
    result = self._engine.execute(request)
    if result.error:
      raise result.error
    # Update the base class indexes for this request.
    for address in self._index(request.roots):
      yield address


class LegacyBuildGraphNode(datatype('LegacyGraphNode', ['target_adaptor', 'dependency_addresses'])):
  """A Node to represent a node in the legacy BuildGraph.

  The ExpGraph implementation inspects only these entries in the ProductGraph.
  """


def reify_legacy_graph(target_adaptor, dependency_nodes):
  """Given a TargetAdaptor and LegacyBuildGraphNodes for its deps, return a LegacyBuildGraphNode."""
  return LegacyBuildGraphNode(target_adaptor,
                              [node.target_adaptor.address for node in dependency_nodes])


def create_legacy_graph_tasks():
  """Create tasks to recursively parse the legacy graph."""
  return [
    # Recursively requests LegacyGraphNodes for TargetAdaptors, which will result in a
    # transitive graph walk.
    (LegacyBuildGraphNode,
     [Select(TargetAdaptor),
      SelectDependencies(LegacyBuildGraphNode, TargetAdaptor)],
     reify_legacy_graph),
  ]
