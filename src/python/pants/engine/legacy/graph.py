# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import functools
import logging
from builtins import str, zip
from collections import defaultdict, deque
from contextlib import contextmanager
from os.path import dirname

from future.utils import iteritems
from twitter.common.collections import OrderedSet

from pants.base.exceptions import TargetDefinitionException
from pants.base.parse_context import ParseContext
from pants.base.specs import AscendantAddresses, DescendantAddresses, SingleAddress, Specs
from pants.build_graph.address import Address
from pants.build_graph.address_lookup_error import AddressLookupError
from pants.build_graph.app_base import AppBase, Bundle
from pants.build_graph.build_graph import BuildGraph
from pants.build_graph.remote_sources import RemoteSources
from pants.engine.addressable import BuildFileAddresses
from pants.engine.fs import PathGlobs, Snapshot
from pants.engine.legacy.address_mapper import LegacyAddressMapper
from pants.engine.legacy.structs import BundleAdaptor, BundlesField, SourcesField, TargetAdaptor
from pants.engine.mapper import AddressMapper
from pants.engine.rules import RootRule, TaskRule, rule
from pants.engine.selectors import Get, Select
from pants.option.global_options import GlobMatchErrorBehavior
from pants.source.filespec import any_matches_filespec
from pants.source.wrapped_globs import EagerFilesetWithSpec, FilesetRelPathWrapper
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


class _DestWrapper(datatype(['target_types'])):
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
      if issubclass(target_cls, AppBase):
        return self._instantiate_app(target_cls, kwargs)
      elif target_cls is RemoteSources:
        return self._instantiate_remote_sources(kwargs)
      return target_cls(build_graph=self, **kwargs)
    except TargetDefinitionException:
      raise
    except Exception as e:
      raise TargetDefinitionException(
          target_adaptor.address,
          'Failed to instantiate Target with type {}: {}'.format(target_cls, e))

  def _instantiate_app(self, target_cls, kwargs):
    """For App targets, convert BundleAdaptor to BundleProps."""
    parse_context = ParseContext(kwargs['address'].spec_path, dict())
    bundleprops_factory = Bundle(parse_context)
    kwargs['bundles'] = [
      bundleprops_factory.create_bundle_props(bundle)
      for bundle in kwargs['bundles']
    ]

    return target_cls(build_graph=self, **kwargs)

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
    dependencies = tuple(SingleAddress(a.spec_path, a.target_name) for a in addresses)
    specs = [Specs(dependencies=tuple(dependencies))]
    for _ in self._inject_specs(specs):
      pass

  def inject_roots_closure(self, target_roots, fail_fast=None):
    for address in self._inject_specs(target_roots.specs):
      yield address

  def inject_specs_closure(self, specs, fail_fast=None):
    specs = [Specs(dependencies=tuple(specs))]
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
    if not subjects:
      return

    logger.debug('Injecting specs to %s: %s', self, subjects)
    with self._resolve_context():
      thts, = self._scheduler.product_request(TransitiveHydratedTargets,
                                              subjects)

    self._index(thts.closure)

    for hydrated_target in thts.roots:
      yield hydrated_target.address


class _DependentGraph(object):
  """A graph for walking dependent addresses of TargetAdaptor objects.

  This avoids/imitates constructing a v1 BuildGraph object, because that codepath results
  in many references held in mutable global state (ie, memory leaks).

  The long term goal is to deprecate the `changed` goal in favor of sufficiently good cache
  hit rates, such that rather than running:

    ./pants --changed-parent=master test

  ...you would always be able to run:

    ./pants test ::

  ...and have it complete in a similar amount of time by hitting relevant caches.
  """

  @classmethod
  def from_iterable(cls, target_types, address_mapper, adaptor_iter):
    """Create a new DependentGraph from an iterable of TargetAdaptor subclasses."""
    inst = cls(target_types, address_mapper)
    all_valid_addresses = set()
    for target_adaptor in adaptor_iter:
      inst._inject_target(target_adaptor)
      all_valid_addresses.add(target_adaptor.address)
    inst._validate(all_valid_addresses)
    return inst

  def __init__(self, target_types, address_mapper):
    # TODO: Dependencies and implicit dependencies are mapped independently, because the latter
    # cannot be validated until:
    #  1) Subsystems are computed in engine: #5869. Currently instantiating a subsystem to find
    #     its injectable specs would require options parsing.
    #  2) Targets-class Subsystem deps can be expanded in-engine (similar to Fields): #4535,
    self._dependent_address_map = defaultdict(set)
    self._implicit_dependent_address_map = defaultdict(set)
    self._target_types = target_types
    self._address_mapper = address_mapper

  def _validate(self, all_valid_addresses):
    """Validate that all of the dependencies in the graph exist in the given addresses set."""
    for dependency, dependents in iteritems(self._dependent_address_map):
      if dependency not in all_valid_addresses:
        raise AddressLookupError(
            'Dependent graph construction failed: {} did not exist. Was depended on by:\n  {}'.format(
             dependency.spec,
             '\n  '.join(d.spec for d in dependents)
          )
        )

  def _inject_target(self, target_adaptor):
    """Inject a target, respecting all sources of dependencies."""
    target_cls = self._target_types[target_adaptor.type_alias]

    declared_deps = target_adaptor.dependencies
    implicit_deps = (Address.parse(s,
                                   relative_to=target_adaptor.address.spec_path,
                                   subproject_roots=self._address_mapper.subproject_roots)
                     for s in target_cls.compute_dependency_specs(kwargs=target_adaptor.kwargs()))
    for dep in declared_deps:
      self._dependent_address_map[dep].add(target_adaptor.address)
    for dep in implicit_deps:
      self._implicit_dependent_address_map[dep].add(target_adaptor.address)

  def dependents_of_addresses(self, addresses):
    """Given an iterable of addresses, yield all of those addresses dependents."""
    seen = OrderedSet(addresses)
    for address in addresses:
      seen.update(self._dependent_address_map[address])
      seen.update(self._implicit_dependent_address_map[address])
    return seen

  def transitive_dependents_of_addresses(self, addresses):
    """Given an iterable of addresses, yield all of those addresses dependents, transitively."""
    closure = set()
    result = []
    to_visit = deque(addresses)

    while to_visit:
      address = to_visit.popleft()
      if address in closure:
        continue

      closure.add(address)
      result.append(address)
      to_visit.extend(self._dependent_address_map[address])
      to_visit.extend(self._implicit_dependent_address_map[address])

    return result


class HydratedTarget(datatype(['address', 'adaptor', 'dependencies'])):
  """A wrapper for a fully hydrated TargetAdaptor object.

  Transitive graph walks collect ordered sets of TransitiveHydratedTargets which involve a huge amount
  of hashing: we implement eq/hash via direct usage of an Address field to speed that up.
  """

  @property
  def addresses(self):
    return self.dependencies

  def __hash__(self):
    return hash(self.address)


class TransitiveHydratedTarget(datatype(['root', 'dependencies'])):
  """A recursive structure wrapping a HydratedTarget root and TransitiveHydratedTarget deps."""


class TransitiveHydratedTargets(datatype(['roots', 'closure'])):
  """A set of HydratedTarget roots, and their transitive, flattened, de-duped closure."""


class HydratedTargets(Collection.of(HydratedTarget)):
  """An intransitive set of HydratedTarget objects."""


class OwnersRequest(datatype([
  ('sources', tuple),
  ('include_dependees', str),
])):
  """A request for the owners (and optionally, transitive dependees) of a set of file paths.

  TODO: `include_dependees` should become an `enum` of the choices from the
  `--changed-include-dependees` global option.
  """


def find_owners(symbol_table, address_mapper, owners_request):
  sources_set = OrderedSet(owners_request.sources)
  dirs_set = OrderedSet(dirname(source) for source in sources_set)

  # Walk up the buildroot looking for targets that would conceivably claim changed sources.
  candidate_specs = tuple(AscendantAddresses(directory=d) for d in dirs_set)
  candidate_targets = yield Get(HydratedTargets, Specs(candidate_specs))

  # Match the source globs against the expanded candidate targets.
  def owns_any_source(legacy_target):
    """Given a `HydratedTarget` instance, check if it owns the given source file."""
    target_kwargs = legacy_target.adaptor.kwargs()

    # Handle `sources`-declaring targets.
    # NB: Deleted files can only be matched against the 'filespec' (ie, `PathGlobs`) for a target,
    # so we don't actually call `fileset.matches` here.
    # TODO: This matching logic should be implemented using the rust `fs` crate for two reasons:
    #  1) having two implementations isn't great
    #  2) we're expanding sources via HydratedTarget, but it isn't necessary to do that to match
    target_sources = target_kwargs.get('sources', None)
    if target_sources and any_matches_filespec(sources_set, target_sources.filespec):
      return True

    return False

  direct_owners = tuple(ht.adaptor.address
                        for ht in candidate_targets.dependencies
                        if LegacyAddressMapper.any_is_declaring_file(ht.adaptor.address, sources_set) or
                           owns_any_source(ht))

  # If the OwnersRequest does not require dependees, then we're done.
  if owners_request.include_dependees == 'none':
    yield BuildFileAddresses(direct_owners)
  else:
    # Otherwise: find dependees.
    all_addresses = yield Get(BuildFileAddresses, Specs((DescendantAddresses(''),)))
    all_structs = yield [Get(symbol_table.constraint(), Address, a.to_address()) for a in all_addresses.dependencies]

    graph = _DependentGraph.from_iterable(target_types_from_symbol_table(symbol_table),
                                          address_mapper,
                                          all_structs)
    if owners_request.include_dependees == 'direct':
      yield BuildFileAddresses(tuple(graph.dependents_of_addresses(direct_owners)))
    else:
      assert owners_request.include_dependees == 'transitive'
      yield BuildFileAddresses(tuple(graph.transitive_dependents_of_addresses(direct_owners)))


@rule(TransitiveHydratedTargets, [Select(BuildFileAddresses)])
def transitive_hydrated_targets(build_file_addresses):
  """Given BuildFileAddresses, kicks off recursion on expansion of TransitiveHydratedTargets.

  The TransitiveHydratedTarget struct represents a structure-shared graph, which we walk
  and flatten here. The engine memoizes the computation of TransitiveHydratedTarget, so
  when multiple TransitiveHydratedTargets objects are being constructed for multiple
  roots, their structure will be shared.
  """

  transitive_hydrated_targets = yield [Get(TransitiveHydratedTarget, Address, a)
                                       for a in build_file_addresses.addresses]

  closure = set()
  to_visit = deque(transitive_hydrated_targets)

  while to_visit:
    tht = to_visit.popleft()
    if tht.root in closure:
      continue
    closure.add(tht.root)
    to_visit.extend(tht.dependencies)

  yield TransitiveHydratedTargets(tuple(tht.root for tht in transitive_hydrated_targets), closure)


@rule(TransitiveHydratedTarget, [Select(HydratedTarget)])
def transitive_hydrated_target(root):
  dependencies = yield [Get(TransitiveHydratedTarget, Address, d) for d in root.dependencies]
  yield TransitiveHydratedTarget(root, dependencies)


@rule(HydratedTargets, [Select(BuildFileAddresses)])
def hydrated_targets(build_file_addresses):
  """Requests HydratedTarget instances for BuildFileAddresses."""
  targets = yield [Get(HydratedTarget, Address, a) for a in build_file_addresses.addresses]
  yield HydratedTargets(targets)


class HydratedField(datatype(['name', 'value'])):
  """A wrapper for a fully constructed replacement kwarg for a HydratedTarget."""


def hydrate_target(target_adaptor):
  """Construct a HydratedTarget from a TargetAdaptor and hydrated versions of its adapted fields."""
  # Hydrate the fields of the adaptor and re-construct it.
  hydrated_fields = yield [(Get(HydratedField, BundlesField, fa)
                            if type(fa) is BundlesField
                            else Get(HydratedField, SourcesField, fa))
                           for fa in target_adaptor.field_adaptors]
  kwargs = target_adaptor.kwargs()
  for field in hydrated_fields:
    kwargs[field.name] = field.value
  yield HydratedTarget(target_adaptor.address,
                        TargetAdaptor(**kwargs),
                        tuple(target_adaptor.dependencies))


def _eager_fileset_with_spec(spec_path, filespec, snapshot, include_dirs=False):
  rel_include_globs = filespec['globs']

  relpath_adjusted_filespec = FilesetRelPathWrapper.to_filespec(rel_include_globs, spec_path)
  if 'exclude' in filespec:
    relpath_adjusted_filespec['exclude'] = [FilesetRelPathWrapper.to_filespec(e['globs'], spec_path)
                                            for e in filespec['exclude']]

  return EagerFilesetWithSpec(spec_path,
                              relpath_adjusted_filespec,
                              snapshot,
                              include_dirs=include_dirs)


@rule(HydratedField, [Select(SourcesField), Select(GlobMatchErrorBehavior)])
def hydrate_sources(sources_field, glob_match_error_behavior):
  """Given a SourcesField, request a Snapshot for its path_globs and create an EagerFilesetWithSpec.
  """
  # TODO(#5864): merge the target's selection of --glob-expansion-failure (which doesn't exist yet)
  # with the global default!
  path_globs = sources_field.path_globs.copy(glob_match_error_behavior=glob_match_error_behavior)
  snapshot = yield Get(Snapshot, PathGlobs, path_globs)
  fileset_with_spec = _eager_fileset_with_spec(
    sources_field.address.spec_path,
    sources_field.filespecs,
    snapshot)
  sources_field.validate_fn(fileset_with_spec)
  yield HydratedField(sources_field.arg, fileset_with_spec)


@rule(HydratedField, [Select(BundlesField), Select(GlobMatchErrorBehavior)])
def hydrate_bundles(bundles_field, glob_match_error_behavior):
  """Given a BundlesField, request Snapshots for each of its filesets and create BundleAdaptors."""
  path_globs_with_match_errors = [
    pg.copy(glob_match_error_behavior=glob_match_error_behavior)
    for pg in bundles_field.path_globs_list
  ]
  snapshot_list = yield [Get(Snapshot, PathGlobs, pg) for pg in path_globs_with_match_errors]

  spec_path = bundles_field.address.spec_path

  bundles = []
  zipped = zip(bundles_field.bundles,
               bundles_field.filespecs_list,
               snapshot_list)
  for bundle, filespecs, snapshot in zipped:
    rel_spec_path = getattr(bundle, 'rel_path', spec_path)
    kwargs = bundle.kwargs()
    # NB: We `include_dirs=True` because bundle filesets frequently specify directories in order
    # to trigger a (deprecated) default inclusion of their recursive contents. See the related
    # deprecation in `pants.backend.jvm.tasks.bundle_create`.
    kwargs['fileset'] = _eager_fileset_with_spec(rel_spec_path,
                                                 filespecs,
                                                 snapshot,
                                                 include_dirs=True)
    bundles.append(BundleAdaptor(**kwargs))
  yield HydratedField('bundles', bundles)


def create_legacy_graph_tasks(symbol_table):
  """Create tasks to recursively parse the legacy graph."""
  symbol_table_constraint = symbol_table.constraint()

  partial_find_owners = functools.partial(find_owners, symbol_table)
  functools.update_wrapper(partial_find_owners, find_owners)

  return [
    transitive_hydrated_targets,
    transitive_hydrated_target,
    hydrated_targets,
    TaskRule(
      HydratedTarget,
      [Select(symbol_table_constraint)],
      hydrate_target,
      input_gets=[
        Get(HydratedField, SourcesField),
        Get(HydratedField, BundlesField),
      ]
    ),
    TaskRule(
      BuildFileAddresses,
      [Select(AddressMapper), Select(OwnersRequest)],
      partial_find_owners,
      input_gets=[
        Get(HydratedTargets, Specs),
        Get(BuildFileAddresses, Specs),
        Get(symbol_table_constraint, Address),
      ]
    ),
    hydrate_sources,
    hydrate_bundles,
    RootRule(OwnersRequest),
  ]
