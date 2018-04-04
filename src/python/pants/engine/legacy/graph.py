# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
from collections import deque
from contextlib import contextmanager

from twitter.common.collections import OrderedSet

from pants.backend.jvm.targets.jvm_app import Bundle, JvmApp
from pants.base.exceptions import TargetDefinitionException
from pants.base.parse_context import ParseContext
from pants.base.specs import SingleAddress, Specs
from pants.build_graph.address import Address
from pants.build_graph.address_lookup_error import AddressLookupError
from pants.build_graph.build_graph import BuildGraph
from pants.build_graph.remote_sources import RemoteSources
from pants.engine.addressable import BuildFileAddresses
from pants.engine.fs import PathGlobs, Snapshot
from pants.engine.legacy.structs import BundleAdaptor, BundlesField, SourcesField, TargetAdaptor
from pants.engine.rules import TaskRule, rule
from pants.engine.selectors import Select, SelectDependencies, SelectProjection
from pants.source.wrapped_globs import EagerFilesetWithSpec, FilesetRelPathWrapper
from pants.util.dirutil import fast_relpath
from pants.util.objects import Collection, datatype


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

  def _index(self, hydrated_targets):
    """Index from the given roots into the storage provided by the base class.

    This is an additive operation: any existing connections involving these nodes are preserved.
    """
    all_addresses = set()
    new_targets = list()

    # Index the ProductGraph.
    for hydrated_target in hydrated_targets:
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
    for _ in self._inject_specs([SingleAddress(a.spec_path, a.target_name) for a in addresses]):
      pass

  def inject_roots_closure(self, target_roots, fail_fast=None):
    for address in self._inject_specs(target_roots.specs):
      yield address

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
    except Exception as e:
      raise AddressLookupError(
        'Build graph construction failed: {} {}'.format(type(e).__name__, str(e))
      )

  def _inject_addresses(self, subjects):
    """Injects targets into the graph for each of the given `Address` objects, and then yields them.

    TODO: See #5606 about undoing the split between `_inject_addresses` and `_inject_specs`.
    """
    logger.debug('Injecting addresses to %s: %s', self, subjects)
    with self._resolve_context():
      addresses = tuple(subjects)
      thts, = self._scheduler.product_request(TransitiveHydratedTargets,
                                              [BuildFileAddresses(addresses)])

    self._index(thts.closure)

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
      specs = tuple(subjects)
      thts, = self._scheduler.product_request(TransitiveHydratedTargets,
                                              [Specs(specs)])

    self._index(thts.closure)

    for hydrated_target in thts.roots:
      yield hydrated_target.address


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


class TransitiveHydratedTarget(datatype('TransitiveHydratedTarget', ['root', 'dependencies'])):
  """A recursive structure wrapping a HydratedTarget root and TransitiveHydratedTarget deps."""


class TransitiveHydratedTargets(datatype('TransitiveHydratedTargets', ['roots', 'closure'])):
  """A set of HydratedTarget roots, and their transitive, flattened, de-duped closure."""


class HydratedTargets(Collection.of(HydratedTarget)):
  """An intransitive set of HydratedTarget objects."""


@rule(TransitiveHydratedTargets, [SelectDependencies(TransitiveHydratedTarget,
                                                     BuildFileAddresses,
                                                     field_types=(Address,),
                                                     field='addresses')])
def transitive_hydrated_targets(transitive_hydrated_targets):
  """Kicks off recursion on expansion of TransitiveHydratedTarget objects.

  The TransitiveHydratedTarget struct represents a structure-shared graph, which we walk
  and flatten here. The engine memoizes the computation of TransitiveHydratedTarget, so
  when multiple TransitiveHydratedTargets objects are being constructed for multiple
  roots, their structure will be shared.
  """
  closure = set()
  to_visit = deque(transitive_hydrated_targets)

  while to_visit:
    tht = to_visit.popleft()
    if tht.root in closure:
      continue
    closure.add(tht.root)
    to_visit.extend(tht.dependencies)

  return TransitiveHydratedTargets(tuple(tht.root for tht in transitive_hydrated_targets), closure)


@rule(TransitiveHydratedTarget, [Select(HydratedTarget),
                                 SelectDependencies(TransitiveHydratedTarget,
                                                    HydratedTarget,
                                                    field_types=(Address,),
                                                    field='addresses')])
def transitive_hydrated_target(root, dependencies):
  return TransitiveHydratedTarget(root, dependencies)


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
    transitive_hydrated_target,
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
