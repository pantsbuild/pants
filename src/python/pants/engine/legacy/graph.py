# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import itertools
import logging

from twitter.common.collections import OrderedSet

from pants.backend.jvm.targets.jvm_app import Bundle, JvmApp
from pants.base.exceptions import TargetDefinitionException
from pants.base.parse_context import ParseContext
from pants.base.specs import SingleAddress
from pants.build_graph.address import Address
from pants.build_graph.address_lookup_error import AddressLookupError
from pants.build_graph.build_graph import BuildGraph
from pants.build_graph.remote_sources import RemoteSources
from pants.build_graph.target import Target
from pants.engine.addressable import BuildFileAddresses, Collection
from pants.engine.fs import PathGlobs, Snapshot
from pants.engine.legacy.structs import BundleAdaptor, BundlesField, SourcesField, TargetAdaptor
from pants.engine.mapper import ResolveError
from pants.engine.nodes import Return
from pants.engine.rules import TaskRule, rule
from pants.engine.selectors import Select, SelectDependencies, SelectProjection, SelectTransitive
from pants.source.wrapped_globs import EagerFilesetWithSpec, FilesetRelPathWrapper
from pants.util.dirutil import fast_relpath
from pants.util.objects import datatype


logger = logging.getLogger(__name__)


class _DestWrapper(datatype('DestWrapper', ['target_types'])):
  """A wrapper for dest field of RemoteSources target.

  This is only used when instantiating RemoteSources target.
  """


class LegacyBuildGraph(BuildGraph):
  """A directed acyclic graph of Targets and dependencies. Not necessarily connected.

  This implementation is backed by a Scheduler that is able to resolve HydratedTargets.
  """

  class InvalidCommandLineSpecError(AddressLookupError):
    """Raised when command line spec is not a valid directory"""

  @classmethod
  def create(cls, scheduler, engine, symbol_table_cls, include_trace_on_error=True):
    """Construct a graph given a Scheduler, Engine, and a SymbolTable class."""
    return cls(scheduler, engine, cls._get_target_types(symbol_table_cls), include_trace_on_error=include_trace_on_error)

  def __init__(self, scheduler, engine, target_types, include_trace_on_error=True):
    """Construct a graph given a Scheduler, Engine, and a SymbolTable class.

    :param scheduler: A Scheduler that is configured to be able to resolve HydratedTargets.
    :param engine: An Engine subclass to execute calls to `inject`.
    :param symbol_table_cls: A SymbolTable class used to instantiate Target objects. Must match
      the symbol table installed in the scheduler (TODO: see comment in `_instantiate_target`).
    """
    self._include_trace_on_error = include_trace_on_error
    self._scheduler = scheduler
    self._engine = engine
    self._target_types = target_types
    super(LegacyBuildGraph, self).__init__()

  def clone_new(self):
    """Returns a new BuildGraph instance of the same type and with the same __init__ params."""
    return LegacyBuildGraph(self._scheduler, self._engine, self._target_types)

  @staticmethod
  def _get_target_types(symbol_table_cls):
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
    for node, state in roots.items():
      self._assert_type_is_return(node, state)
      self._assert_correct_value_type(state, HydratedTargets)
      # We have a successful HydratedTargets value (for a particular input Spec).
      for hydrated_target in state.value.dependencies:
        target_adaptor = hydrated_target.adaptor
        address = target_adaptor.address
        all_addresses.add(address)
        if address not in self._target_by_address:
          new_targets.append(self._index_target(target_adaptor))

    # Once the declared dependencies of all targets are indexed, inject their
    # additional "traversable_(dependency_)?specs".
    deps_to_inject = OrderedSet()
    addresses_to_inject = set()
    def inject(target, dep_spec, is_dependency):
      address = Address.parse(dep_spec, relative_to=target.address.spec_path)
      if not any(address == t.address for t in target.dependencies):
        addresses_to_inject.add(address)
        if is_dependency:
          deps_to_inject.add((target.address, address))

    self.apply_injectables(new_targets)

    for target in new_targets:
      traversables = [target.compute_dependency_specs(payload=target.payload)]
      # Only poke `traversable_dependency_specs` if a concrete implementation is defined
      # in order to avoid spurious deprecation warnings.
      if type(target).traversable_dependency_specs is not Target.traversable_dependency_specs:
        traversables.append(target.traversable_dependency_specs)
      for spec in itertools.chain(*traversables):
        inject(target, spec, is_dependency=True)

      traversables = [target.compute_injectable_specs(payload=target.payload)]
      if type(target).traversable_specs is not Target.traversable_specs:
        traversables.append(target.traversable_specs)
      for spec in itertools.chain(*traversables):
        inject(target, spec, is_dependency=False)

    # Inject all addresses, then declare injected dependencies.
    self.inject_addresses_closure(addresses_to_inject)
    for target_address, dep_address in deps_to_inject:
      self.inject_dependency(dependent=target_address, dependency=dep_address)

    return all_addresses

  def _index_target(self, target_adaptor):
    """Instantiate the given TargetAdaptor, index it in the graph, and return a Target."""
    # Instantiate the target.
    address = target_adaptor.address
    target = self._instantiate_target(target_adaptor)
    self._target_by_address[address] = target

    # Link its declared dependencies, which will be indexed independently.
    self._target_dependencies_by_address[address].update(target_adaptor.dependencies)
    for dependency in target_adaptor.dependencies:
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
      elif target_cls is RemoteSources:
        return self._instantiate_remote_sources(kwargs)
      return target_cls(build_graph=self, **kwargs)
    except TargetDefinitionException:
      raise
    except Exception as e:
      raise TargetDefinitionException(
          target_adaptor.address,
          'Failed to instantiate Target with type {}: {}'.format(target_cls, e))

  def _instantiate_jvm_app(self, kwargs):
    """For JvmApp target, convert BundleAdaptor to BundleProps."""
    parse_context = ParseContext(kwargs['address'].spec_path, dict())
    bundleprops_factory = Bundle(parse_context)
    kwargs['bundles'] = [
      bundleprops_factory.create_bundle_props(bundle)
      for bundle in kwargs['bundles']
    ]

    return JvmApp(build_graph=self, **kwargs)

  def _instantiate_remote_sources(self, kwargs):
    """For RemoteSources target, convert "dest" field to its real target type."""
    kwargs['dest'] = _DestWrapper((self._target_types[kwargs['dest']],))
    return RemoteSources(build_graph=self, **kwargs)

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
    self.inject_addresses_closure([address])

  def inject_addresses_closure(self, addresses):
    addresses = set(addresses) - set(self._target_by_address.keys())
    if not addresses:
      return
    matched = set(self._inject([SingleAddress(a.spec_path, a.target_name) for a in addresses]))
    missing = addresses - matched
    if missing:
      # TODO: When SingleAddress resolution converted from projection of a directory
      # and name to a match for PathGlobs, we lost our useful AddressLookupError formatting.
      raise AddressLookupError('Addresses were not matched: {}'.format(missing))

  def inject_specs_closure(self, specs, fail_fast=None):
    # Request loading of these specs.
    for address in self._inject(specs):
      yield address

  def resolve_address(self, address):
    if not self.contains_address(address):
      self.inject_address_closure(address)
    return self.get_target(address)

  def _inject(self, subjects):
    """Inject Targets into the graph for each of the subjects and yield the resulting addresses."""
    logger.debug('Injecting to %s: %s', self, subjects)
    request = self._scheduler.execution_request([HydratedTargets, BuildFileAddresses], subjects)

    result = self._engine.execute(request)
    if result.error:
      raise result.error
    # Update the base class indexes for this request.
    root_entries = result.root_products
    address_entries = {k: v for k, v in root_entries.items() if k[1].product is BuildFileAddresses}
    target_entries = {k: v for k, v in root_entries.items() if k[1].product is HydratedTargets}
    self._index(target_entries)

    yielded_addresses = set()
    for (subject, _), state in address_entries.items():
      self._assert_type_is_return(subject, state)
      self._assert_correct_value_type(state, BuildFileAddresses)

      if not state.value.dependencies:
        raise self.InvalidCommandLineSpecError(
          'Spec {} does not match any targets.'.format(subject))
      for address in state.value.dependencies:
        if address not in yielded_addresses:
          yielded_addresses.add(address)
          yield address

  def _assert_type_is_return(self, node, state):
    # TODO Verifying the type is return should be handled in a more central way.
    #      It's related to the clean up tracked via https://github.com/pantsbuild/pants/issues/4229
    if type(state) is Return:
      return

    # NB: ResolveError means that a target was not found, which is a common user facing error.
    # TODO Come up with a better error reporting mechanism so that we don't need this as a special case.
    #      Possibly as part of https://github.com/pantsbuild/pants/issues/4446
    if isinstance(state.exc, ResolveError):
      raise AddressLookupError(str(state.exc))
    else:
      if self._include_trace_on_error:
        trace = '\n'.join(self._scheduler.trace())
        raise AddressLookupError(
          'Build graph construction failed for {}:\n{}'.format(node, trace))
      else:
        raise AddressLookupError(
          'Build graph construction failed for {}: {} {}'
            .format(node,
                    type(state.exc).__name__,
                    str(state.exc))
        )

  def _assert_correct_value_type(self, state, expected_type):
    # TODO This is a pretty general assertion, and it should live closer to where the result is generated.
    #      It's related to the clean up tracked via https://github.com/pantsbuild/pants/issues/4229
    if type(state.value) is not expected_type:
      raise TypeError('Expected roots to hold {}; got: {}'.format(
        expected_type, type(state.value)))


class HydratedTarget(datatype('HydratedTarget', ['address', 'adaptor', 'dependencies'])):
  """A wrapper for a fully hydrated TargetAdaptor object.

  Transitive graph walks collect ordered sets of HydratedTargets which involve a huge amount
  of hashing: we implement eq/hash via direct usage of an Address field to speed that up.
  """

  @property
  def addresses(self):
    return self.dependencies

  def __eq__(self, other):
    if type(self) != type(other):
      return False
    return self.address == other.address

  def __ne__(self, other):
    return not (self == other)

  def __hash__(self):
    return hash(self.address)


HydratedTargets = Collection.of(HydratedTarget)


@rule(HydratedTargets, [SelectTransitive(HydratedTarget, BuildFileAddresses, field_types=(Address,), field='addresses')])
def transitive_hydrated_targets(targets):
  """Recursively requests HydratedTargets, which will result in an eager, transitive graph walk."""
  return HydratedTargets(targets)


class HydratedField(datatype('HydratedField', ['name', 'value'])):
  """A wrapper for a fully constructed replacement kwarg for a HydratedTarget."""


def hydrate_target(target_adaptor, hydrated_fields):
  """Construct a HydratedTarget from a TargetAdaptor and hydrated versions of its adapted fields."""
  # Hydrate the fields of the adaptor and re-construct it.
  kwargs = target_adaptor.kwargs()
  for field in hydrated_fields:
    kwargs[field.name] = field.value
  return HydratedTarget(target_adaptor.address,
                        TargetAdaptor(**kwargs),
                        tuple(target_adaptor.dependencies))


def _eager_fileset_with_spec(spec_path, filespec, snapshot):
  files = tuple(fast_relpath(fd.path, spec_path) for fd in snapshot.files)

  relpath_adjusted_filespec = FilesetRelPathWrapper.to_filespec(filespec['globs'], spec_path)
  if filespec.has_key('exclude'):
    relpath_adjusted_filespec['exclude'] = [FilesetRelPathWrapper.to_filespec(e['globs'], spec_path)
                                            for e in filespec['exclude']]

  # NB: In order to preserve declared ordering, we record a list of matched files
  # independent of the file hash dict.
  return EagerFilesetWithSpec(spec_path,
                              relpath_adjusted_filespec,
                              files=files,
                              files_hash=snapshot.fingerprint)


@rule(HydratedField,
      [Select(SourcesField),
       SelectProjection(Snapshot, PathGlobs, 'path_globs', SourcesField)])
def hydrate_sources(sources_field, snapshot):
  """Given a SourcesField and a Snapshot for its path_globs, create an EagerFilesetWithSpec."""
  fileset_with_spec = _eager_fileset_with_spec(sources_field.address.spec_path,
                                               sources_field.filespecs,
                                               snapshot)
  return HydratedField(sources_field.arg, fileset_with_spec)


@rule(HydratedField,
      [Select(BundlesField),
       SelectDependencies(Snapshot, BundlesField, 'path_globs_list', field_types=(PathGlobs,))])
def hydrate_bundles(bundles_field, snapshot_list):
  """Given a BundlesField and a Snapshot for each of its filesets create a list of BundleAdaptors."""
  bundles = []
  zipped = zip(bundles_field.bundles,
               bundles_field.filespecs_list,
               snapshot_list)
  for bundle, filespecs, snapshot in zipped:
    spec_path = bundles_field.address.spec_path
    kwargs = bundle.kwargs()
    kwargs['fileset'] = _eager_fileset_with_spec(getattr(bundle, 'rel_path', spec_path),
                                                 filespecs,
                                                 snapshot)
    bundles.append(BundleAdaptor(**kwargs))
  return HydratedField('bundles', bundles)


def create_legacy_graph_tasks(symbol_table_cls):
  """Create tasks to recursively parse the legacy graph."""
  symbol_table_constraint = symbol_table_cls.constraint()
  return [
    transitive_hydrated_targets,
    TaskRule(
      HydratedTarget,
      [Select(symbol_table_constraint),
       SelectDependencies(HydratedField,
                          symbol_table_constraint,
                          'field_adaptors',
                          field_types=(SourcesField, BundlesField,))],
      hydrate_target
    ),
    hydrate_sources,
    hydrate_bundles,
  ]
