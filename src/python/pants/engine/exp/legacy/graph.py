# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from hashlib import sha1
import logging

from pants.base.exceptions import TargetDefinitionException
from pants.build_graph.address import Address
from pants.build_graph.address_lookup_error import AddressLookupError
from pants.build_graph.build_graph import BuildGraph
from pants.engine.exp.fs import FilesContent, PathGlobs
from pants.engine.exp.legacy.structs import TargetAdaptor
from pants.engine.exp.nodes import Return, SelectNode, State, Throw
from pants.engine.exp.selectors import Select, SelectDependencies, SelectProjection
from pants.source.wrapped_globs import EagerFilesetWithSpec
from pants.util.objects import datatype


logger = logging.getLogger(__name__)


class ExpGraph(BuildGraph):
  """A directed acyclic graph of Targets and dependencies. Not necessarily connected.

  This implementation is backed by a Scheduler that is able to resolve LegacyTargets.
  """

  def __init__(self, scheduler, engine, symbol_table_cls):
    """Construct a graph given a Scheduler, Engine, and a SymbolTable class.

    :param scheduler: A Scheduler that is configured to be able to resolve LegacyTargets.
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
    all_addresses = set()
    new_targets = list()

    # Index the ProductGraph.
    for node, state in self._graph.walk(roots=roots):
      # Locate nodes that contain LegacyTarget values.
      if type(state) is Throw:
        raise AddressLookupError(
            'Build graph construction failed for {}:\n  {}'.format(node.subject, state.exc))
      elif type(state) is not Return:
        State.raise_unrecognized(state)
      if node.product is not LegacyTarget:
        continue
      if type(node) is not SelectNode:
        continue

      # We have a successfully parsed LegacyTarget, which includes its declared dependencies
      # and sources.
      address = state.value.adaptor.address
      all_addresses.add(address)
      if address not in self._target_by_address:
        new_targets.append(self._index_target(state.value))

    # Once the declared dependencies of all targets are indexed, inject their
    # additional "traversable_(dependency_)?specs".
    deps_to_inject = set()
    addresses_to_inject = set()
    def inject(target, dep_spec, is_dependency):
      address = Address.parse(dep_spec, relative_to=target.address.spec_path)
      if not any(address == t.address for t in target.dependencies):
        addresses_to_inject.add(address)
        if is_dependency:
          deps_to_inject.add((target.address, address))

    for target in new_targets:
      for spec in target.traversable_dependency_specs:
        inject(target, spec, is_dependency=True)
      for spec in target.traversable_specs:
        inject(target, spec, is_dependency=False)

    # Inject all addresses, then declare injected dependencies.
    self.inject_addresses_closure(addresses_to_inject)
    for target_address, dep_address in deps_to_inject:
      self.inject_dependency(dependent=target_address, dependency=dep_address)

    return all_addresses

  def _index_target(self, legacy_target):
    """Instantiate the given LegacyTarget, index it in the graph, and return a Target."""
    # Instantiate the target.
    address = legacy_target.adaptor.address
    target = self._instantiate_target(legacy_target.adaptor, legacy_target.sources)
    self._target_by_address[address] = target

    # Link its declared dependencies, which will be indexed independently.
    self._target_dependencies_by_address[address].update(legacy_target.dependencies)
    for dependency in legacy_target.dependencies:
      self._target_dependees_by_address[dependency].add(address)
    return target

  def _instantiate_target(self, target_adaptor, fileset_with_spec):
    """Given a TargetAdaptor struct previously parsed from a BUILD file, instantiate a Target.

    TODO: This assumes that the SymbolTable used for parsing matches the SymbolTable passed
    to this graph. Would be good to make that more explicit, but it might be better to nuke
    the Target subclassing pattern instead, and lean further into the "configuration composition"
    model explored in the `exp` package.
    """
    target_cls = self._target_types[target_adaptor.type_alias]
    try:
      # Pop dependencies/sources/spec_path, which were already consumed during construction.
      kwargs = target_adaptor.kwargs()
      kwargs.pop('dependencies')
      # Replace the sources argument with a FilesetWithSpecs instance, or None.
      kwargs.pop('spec_path')
      if sources in kwargs:
        kwargs['sources'] = fileset_with_spec
      # Instantiate.
      return target_cls(build_graph=self, **kwargs)
    except TargetDefinitionException:
      raise
    except Exception as e:
      raise TargetDefinitionException(
          target_adaptor.address,
          'Failed to instantiate Target with type {}: {}'.format(target_cls, e))

  def inject_synthetic_target(self,
                              address,
                              target_type,
                              dependencies=None,
                              derived_from=None,
                              **kwargs):
    sources = kwargs.get('sources', None)
    if sources is not None:
      kwargs['sources'] = self._instantiate_sources(address.spec_path, sources)
    target = target_type(name=address.target_name,
                         address=address,
                         build_graph=self,
                         **kwargs)
    self.inject_target(target,
                       dependencies=dependencies,
                       derived_from=derived_from,
                       synthetic=True)

  def inject_address_closure(self, address):
    if address in self._target_by_address:
      return
    for _ in self._inject([address]):
      pass

  def inject_addresses_closure(self, addresses):
    addresses = set(addresses) - set(self._target_by_address.keys())
    if not addresses:
      return
    for _ in self._inject(addresses):
      pass

  def inject_specs_closure(self, specs, fail_fast=None):
    # Request loading of these specs.
    for address in self._inject(specs):
      yield address

  def _inject(self, subjects):
    """Request LegacyTargets for each of the subjects, and yield resulting Addresses."""
    logger.debug('Injecting to {}: {}'.format(self, subjects))
    request = self._scheduler.execution_request([LegacyTarget], subjects)
    result = self._engine.execute(request)
    if result.error:
      raise result.error
    # Update the base class indexes for this request.
    for address in self._index(request.roots):
      yield address


class LegacyTarget(datatype('LegacyTarget', ['adaptor', 'dependencies', 'sources'])):
  """A node to represent a node in the legacy BuildGraph.

  The ExpGraph implementation inspects only these entries in the ProductGraph.
  """


def reify_legacy_graph(target_adaptor, dependencies, fileset_with_spec):
  """Given a TargetAdaptor and LegacyTargets for its deps, return a LegacyTarget."""
  return LegacyTarget(target_adaptor,
                      [d.target_adaptor.address for d in dependencies],
                      fileset_with_spec)


def base_globs_to_fileset_with_spec(target_adaptor, source_files_content):
  """Given a TargetAdaptor and FilesContent for its source field, create an EagerFilesetWithSpec.
  
  The TargetAdaptor is needed in orderfrom which it was parsed, and the pre-computed FilesContent
  for the BaseGlobs.
  """
  base_globs = target_adaptor.sources_base_globs
  file_hashes = {fc.path: sha1(fc.content).digest() for fc in source_files_content.dependencies}
  return EagerFilesetWithSpec('', base_globs.filespecs, file_hashes)


def create_legacy_graph_tasks():
  """Create tasks to recursively parse the legacy graph."""
  return [
    # Recursively requests LegacyGraphNodes for TargetAdaptors, which will result in a
    # transitive graph walk.
    (LegacyTarget,
     [Select(TargetAdaptor),
      SelectDependencies(LegacyTarget, TargetAdaptor),
      Select(EagerFilesetWithSpec)],
     reify_legacy_graph),
    (EagerFilesetWithSpec,
     [Select(TargetAdaptor),
      SelectProjection(FilesContent, PathGlobs, ('sources_path_globs',), TargetAdaptor)],
     base_globs_to_fileset_with_spec),
  ]
