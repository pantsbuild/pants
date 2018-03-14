# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
from contextlib import contextmanager

from twitter.common.collections import OrderedSet

from pants.backend.jvm.targets.jvm_app import Bundle, JvmApp
from pants.base.exceptions import TargetDefinitionException
from pants.base.parse_context import ParseContext
from pants.base.specs import SingleAddress
from pants.base.target_roots import ChangedTargetRoots, LiteralTargetRoots
from pants.build_graph.address import Address
from pants.build_graph.address_lookup_error import AddressLookupError
from pants.build_graph.build_graph import BuildGraph
from pants.build_graph.remote_sources import RemoteSources
from pants.engine.addressable import BuildFileAddresses, Collection
from pants.engine.fs import PathGlobs, Snapshot
from pants.engine.legacy.structs import BundleAdaptor, BundlesField, SourcesField, TargetAdaptor
from pants.engine.mapper import ResolveError
from pants.engine.rules import TaskRule, rule
from pants.engine.selectors import Select, SelectDependencies, SelectProjection, SelectTransitive
from pants.source.wrapped_globs import EagerFilesetWithSpec, FilesetRelPathWrapper
from pants.util.dirutil import fast_relpath
from pants.util.objects import datatype


logger = logging.getLogger(__name__)


def target_types_from_symbol_table(symbol_table):
  """Given a LegacySymbolTable, return the concrete target types constructed for each alias."""
  aliases = symbol_table.aliases()
  target_types = dict(aliases.target_types)
  for alias, factory in aliases.target_macro_factories.items():
    target_type, = factory.target_types
    target_types[alias] = target_type
  return target_types


class _DestWrapper(datatype('DestWrapper', ['target_types'])):
  """A wrapper for dest field of RemoteSources target.

  This is only used when instantiating RemoteSources target.
  """


class LegacyBuildGraph(BuildGraph):
  """A directed acyclic graph of Targets and dependencies. Not necessarily connected.

  This implementation is backed by a Scheduler that is able to resolve TransitiveHydratedTargets.
  """

  class InvalidCommandLineSpecError(AddressLookupError):
    """Raised when command line spec is not a valid directory"""

  @classmethod
  def create(cls, scheduler, symbol_table):
    """Construct a graph given a Scheduler, Engine, and a SymbolTable class."""
    return cls(scheduler, target_types_from_symbol_table(symbol_table))

  def __init__(self, scheduler, target_types):
    """Construct a graph given a Scheduler, Engine, and a SymbolTable class.

    :param scheduler: A Scheduler that is configured to be able to resolve TransitiveHydratedTargets.
    :param symbol_table: A SymbolTable instance used to instantiate Target objects. Must match
      the symbol table installed in the scheduler (TODO: see comment in `_instantiate_target`).
    """
    self._scheduler = scheduler
    self._target_types = target_types
    super(LegacyBuildGraph, self).__init__()

  def clone_new(self):
    """Returns a new BuildGraph instance of the same type and with the same __init__ params."""
    return LegacyBuildGraph(self._scheduler, self._target_types)

  def _index(self, roots):
    """Index from the given roots into the storage provided by the base class.

    This is an additive operation: any existing connections involving these nodes are preserved.
    """
    all_addresses = set()
    new_targets = list()

    # Index the ProductGraph.
    for product in roots:
      # We have a successful TransitiveHydratedTargets value (for a particular input Spec).
      for hydrated_target in product.dependencies:
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
      for spec in target.compute_dependency_specs(payload=target.payload):
        inject(target, spec, is_dependency=True)

      for spec in target.compute_injectable_specs(payload=target.payload):
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

    for dependency in target_adaptor.dependencies:
      if dependency in self._target_dependencies_by_address[address]:
        raise self.DuplicateAddressError(
          'Addresses in dependencies must be unique. '
          "'{spec}' is referenced more than once by target '{target}'."
          .format(spec=dependency.spec, target=address.spec)
        )
      # Link its declared dependencies, which will be indexed independently.
      self._target_dependencies_by_address[address].add(dependency)
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
    matched = set(self._inject_specs([SingleAddress(a.spec_path, a.target_name) for a in addresses]))
    missing = addresses - matched
    if missing:
      # TODO: When SingleAddress resolution converted from projection of a directory
      # and name to a match for PathGlobs, we lost our useful AddressLookupError formatting.
      raise AddressLookupError('Addresses were not matched: {}'.format(missing))

  def inject_roots_closure(self, target_roots, fail_fast=None):
    if type(target_roots) is ChangedTargetRoots:
      for address in self._inject_addresses(target_roots.addresses):
        yield address
    elif type(target_roots) is LiteralTargetRoots:
      for address in self._inject_specs(target_roots.specs):
        yield address
    else:
      raise ValueError('Unrecognized TargetRoots type: `{}`.'.format(target_roots))

  def inject_specs_closure(self, specs, fail_fast=None):
    # Request loading of these specs.
    for address in self._inject_specs(specs):
      yield address

  def resolve_address(self, address):
    if not self.contains_address(address):
      self.inject_address_closure(address)
    return self.get_target(address)

  @contextmanager
  def _resolve_context(self):
    try:
      yield
    except ResolveError as e:
      # NB: ResolveError means that a target was not found, which is a common user facing error.
      raise AddressLookupError(str(e))
    except Exception as e:
      raise AddressLookupError(
        'Build graph construction failed: {} {}'.format(type(e).__name__, str(e))
      )

  def _inject_addresses(self, subjects):
    """Injects targets into the graph for each of the given `Address` objects, and then yields them.

    TODO: See #4533 about unifying "collection of literal Addresses" with the `Spec` types, which
    would avoid the need for the independent `_inject_addresses` and `_inject_specs` codepaths.
    """
    logger.debug('Injecting addresses to %s: %s', self, subjects)
    with self._resolve_context():
      addresses = tuple(subjects)
      hydrated_targets = self._scheduler.product_request(TransitiveHydratedTargets,
                                                         [BuildFileAddresses(addresses)])

    self._index(hydrated_targets)

    yielded_addresses = set()
    for address in subjects:
      if address not in yielded_addresses:
        yielded_addresses.add(address)
        yield address

  def _inject_specs(self, subjects):
    """Injects targets into the graph for each of the given `Spec` objects.

    Yields the resulting addresses.
    """
    logger.debug('Injecting specs to %s: %s', self, subjects)
    with self._resolve_context():
      product_results = self._scheduler.products_request([TransitiveHydratedTargets, BuildFileAddresses],
                                                         subjects)

    self._index(product_results[TransitiveHydratedTargets])

    yielded_addresses = set()
    for subject, product in zip(subjects, product_results[BuildFileAddresses]):
      if not product.dependencies:
        raise self.InvalidCommandLineSpecError(
          'Spec {} does not match any targets.'.format(subject))
      for address in product.dependencies:
        if address not in yielded_addresses:
          yielded_addresses.add(address)
          yield address


class HydratedTarget(datatype('HydratedTarget', ['address', 'adaptor', 'dependencies'])):
  """A wrapper for a fully hydrated TargetAdaptor object.

  Transitive graph walks collect ordered sets of TransitiveHydratedTargets which involve a huge amount
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


class TransitiveHydratedTargets(Collection.of(HydratedTarget)):
  """A transitive set of HydratedTarget objects."""


class HydratedTargets(Collection.of(HydratedTarget)):
  """An intransitive set of HydratedTarget objects."""


@rule(TransitiveHydratedTargets, [SelectTransitive(HydratedTarget,
                                                   BuildFileAddresses,
                                                   field_types=(Address,),
                                                   field='addresses')])
def transitive_hydrated_targets(targets):
  """Recursively requests HydratedTarget instances, which will result in an eager, transitive graph walk."""
  return TransitiveHydratedTargets(targets)


@rule(HydratedTargets, [SelectDependencies(HydratedTarget,
                                           BuildFileAddresses,
                                           field_types=(Address,),
                                           field='addresses')])
def hydrated_targets(targets):
  """Requests HydratedTarget instances."""
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


def _eager_fileset_with_spec(spec_path, filespec, snapshot, include_dirs=False):
  fds = snapshot.path_stats if include_dirs else snapshot.files
  files = tuple(fast_relpath(fd.path, spec_path) for fd in fds)

  relpath_adjusted_filespec = FilesetRelPathWrapper.to_filespec(filespec['globs'], spec_path)
  if filespec.has_key('exclude'):
    relpath_adjusted_filespec['exclude'] = [FilesetRelPathWrapper.to_filespec(e['globs'], spec_path)
                                            for e in filespec['exclude']]

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
    # NB: We `include_dirs=True` because bundle filesets frequently specify directories in order
    # to trigger a (deprecated) default inclusion of their recursive contents. See the related
    # deprecation in `pants.backend.jvm.tasks.bundle_create`.
    kwargs['fileset'] = _eager_fileset_with_spec(getattr(bundle, 'rel_path', spec_path),
                                                 filespecs,
                                                 snapshot,
                                                 include_dirs=True)
    bundles.append(BundleAdaptor(**kwargs))
  return HydratedField('bundles', bundles)


def create_legacy_graph_tasks(symbol_table):
  """Create tasks to recursively parse the legacy graph."""
  symbol_table_constraint = symbol_table.constraint()
  return [
    transitive_hydrated_targets,
    hydrated_targets,
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
