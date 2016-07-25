# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging

from twitter.common.collections import maybe_list

from pants.backend.jvm.targets.jvm_app import BundleProps, JvmApp
from pants.base.exceptions import TargetDefinitionException
from pants.build_graph.address import Address
from pants.build_graph.address_lookup_error import AddressLookupError
from pants.build_graph.build_graph import BuildGraph
from pants.engine.fs import Files, FilesDigest, PathGlobs
from pants.engine.legacy.structs import BundleAdaptor, BundlesField, SourcesField, TargetAdaptor
from pants.engine.nodes import Return, State, TaskNode, Throw
from pants.engine.selectors import Select, SelectDependencies, SelectProjection
from pants.source.wrapped_globs import EagerFilesetWithSpec
from pants.util.dirutil import fast_relpath
from pants.util.objects import datatype


logger = logging.getLogger(__name__)


class LegacyBuildGraph(BuildGraph):
  """A directed acyclic graph of Targets and dependencies. Not necessarily connected.

  This implementation is backed by a Scheduler that is able to resolve LegacyTargets.
  """

  class InvalidCommandLineSpecError(AddressLookupError):
    """Raised when command line spec is not a valid directory"""

  def __init__(self, scheduler, engine, symbol_table_cls):
    """Construct a graph given a Scheduler, Engine, and a SymbolTable class.

    :param scheduler: A Scheduler that is configured to be able to resolve LegacyTargets.
    :param engine: An Engine subclass to execute calls to `inject`.
    :param symbol_table_cls: A SymbolTable class used to instantiate Target objects. Must match
      the symbol table installed in the scheduler (TODO: see comment in `_instantiate_target`).
    """
    self._scheduler = scheduler
    self._graph = scheduler.product_graph
    self._target_types = self._get_target_types(symbol_table_cls)
    self._engine = engine
    super(LegacyBuildGraph, self).__init__()

  def _get_target_types(self, symbol_table_cls):
    aliases = symbol_table_cls.aliases()
    target_types = dict(aliases.target_types)
    for alias, factory in aliases.target_macro_factories.items():
      target_type, = factory.target_types
      target_types[alias] = target_type
    return target_types

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
        trace = '\n'.join(self._graph.trace(node))
        raise AddressLookupError(
            'Build graph construction failed for {}:\n{}'.format(node.subject, trace))
      elif type(state) is not Return:
        State.raise_unrecognized(state)
      if node.product is not LegacyTarget:
        continue
      if type(node) is not TaskNode:
        continue

      # We have a successfully parsed LegacyTarget, which includes its declared dependencies.
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
    target = self._instantiate_target(legacy_target.adaptor)
    self._target_by_address[address] = target

    # Link its declared dependencies, which will be indexed independently.
    self._target_dependencies_by_address[address].update(legacy_target.dependencies)
    for dependency in legacy_target.dependencies:
      self._target_dependees_by_address[dependency].add(address)
    return target

  def _instantiate_target(self, target_adaptor):
    """Given a TargetAdaptor struct previously parsed from a BUILD file, instantiate a Target.

    TODO: This assumes that the SymbolTable used for parsing matches the SymbolTable passed
    to this graph. Would be good to make that more explicit, but it might be better to nuke
    the Target subclassing pattern instead, and lean further into the "configuration composition"
    model explored in the `exp` package.
    """
    target_cls = self._target_types[target_adaptor.type_alias]
    try:
      # Pop dependencies, which were already consumed during construction.
      kwargs = target_adaptor.kwargs()
      kwargs.pop('dependencies')

      # Instantiate.
      if target_cls is JvmApp:
        return self._instantiate_jvm_app(kwargs)
      return target_cls(build_graph=self, **kwargs)
    except TargetDefinitionException:
      raise
    except Exception as e:
      raise TargetDefinitionException(
          target_adaptor.address,
          'Failed to instantiate Target with type {}: {}'.format(target_cls, e))

  def _instantiate_jvm_app(self, kwargs):
    """For JvmApp target, convert BundleAdaptor to BundleProps."""
    kwargs['bundles'] = [
      BundleProps.create_bundle_props(bundle.kwargs()['fileset'])
      for bundle in kwargs['bundles']
    ]

    return JvmApp(build_graph=self, **kwargs)

  def inject_synthetic_target(self,
                              address,
                              target_type,
                              dependencies=None,
                              derived_from=None,
                              **kwargs):
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
    """Inject Targets into the graph for each of the subjects and yield the resulting addresses."""
    logger.debug('Injecting to {}: {}'.format(self, subjects))
    request = self._scheduler.execution_request([LegacyTarget], subjects)

    result = self._engine.execute(request)
    if result.error:
      raise result.error
    # Update the base class indexes for this request.
    self._index(request.roots)

    existing_addresses = set()
    for root, state in self._scheduler.root_entries(request).items():
      entries = maybe_list(state.value, expected_type=LegacyTarget)
      if not entries:
        raise self.InvalidCommandLineSpecError(
          'Spec {} does not match any targets.'.format(root.subject))
      for legacy_target in entries:
        address = legacy_target.adaptor.address
        if address not in existing_addresses:
          existing_addresses.add(address)
          yield address


class LegacyTarget(datatype('LegacyTarget', ['adaptor', 'dependencies'])):
  """A class to represent a node and edges in the legacy BuildGraph.

  The LegacyBuildGraph implementation inspects only these entries in the ProductGraph.
  """


class HydratedField(datatype('HydratedField', ['name', 'value'])):
  """A wrapper for a fully constructed replacement kwarg for a LegacyTarget."""


def reify_legacy_graph(target_adaptor, dependencies, hydrated_fields):
  """Construct a LegacyTarget from a TargetAdaptor, its deps, and hydrated versions of its adapted fields."""
  kwargs = target_adaptor.kwargs()
  for field in hydrated_fields:
    kwargs[field.name] = field.value
  return LegacyTarget(TargetAdaptor(**kwargs), [d.adaptor.address for d in dependencies])


def _eager_fileset_with_spec(spec_path, filespecs, source_files_digest, excluded_source_files):
  excluded = {f.path for f in excluded_source_files.dependencies}
  file_tuples = [(fast_relpath(fd.path, spec_path), fd.digest)
                 for fd in source_files_digest.dependencies
                 if fd.path not in excluded]
  # NB: In order to preserve declared ordering, we record a list of matched files
  # independent of the file hash dict.
  return EagerFilesetWithSpec(spec_path,
                              filespecs,
                              files=tuple(f for f, _ in file_tuples),
                              file_hashes=dict(file_tuples))


def hydrate_sources(sources_field, source_files_digest, excluded_source_files):
  """Given a SourcesField and FilesDigest for its path_globs, create an EagerFilesetWithSpec."""
  fileset_with_spec = _eager_fileset_with_spec(sources_field.address.spec_path,
                                               sources_field.filespecs,
                                               source_files_digest,
                                               excluded_source_files)
  return HydratedField(sources_field.arg, fileset_with_spec)


def hydrate_bundles(bundles_field, files_digest_list, excluded_files_list):
  """Given a BundlesField and FilesDigest for each of its filesets create a list of BundleAdaptors."""
  bundles = []
  zipped = zip(bundles_field.bundles,
               bundles_field.filespecs_list,
               files_digest_list,
               excluded_files_list)
  for bundle, filespecs, files_digest, excluded_files in zipped:
    spec_path = bundles_field.address.spec_path
    kwargs = bundle.kwargs()
    kwargs['fileset'] = _eager_fileset_with_spec(spec_path,
                                                 filespecs,
                                                 files_digest,
                                                 excluded_files)
    bundles.append(BundleAdaptor(**kwargs))
  return HydratedField('bundles', bundles)


def create_legacy_graph_tasks():
  """Create tasks to recursively parse the legacy graph."""
  return [
    # Recursively requests the dependencies and adapted fields of TargetAdaptors, which
    # will result in an eager, transitive graph walk.
    (LegacyTarget,
     [Select(TargetAdaptor),
      SelectDependencies(LegacyTarget, TargetAdaptor, 'dependencies'),
      SelectDependencies(HydratedField, TargetAdaptor, 'field_adaptors')],
     reify_legacy_graph),
    (HydratedField,
     [Select(SourcesField),
      SelectProjection(FilesDigest, PathGlobs, ('path_globs',), SourcesField),
      SelectProjection(Files, PathGlobs, ('excluded_path_globs',), SourcesField)],
     hydrate_sources),
    (HydratedField,
     [Select(BundlesField),
      SelectDependencies(FilesDigest, BundlesField, 'path_globs_list'),
      SelectDependencies(Files, BundlesField, 'excluded_path_globs_list')],
     hydrate_bundles),
  ]
