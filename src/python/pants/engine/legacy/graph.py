# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
from collections import deque
from contextlib import contextmanager

from twitter.common.collections import OrderedSet

from pants.base.exceptions import TargetDefinitionException
from pants.base.parse_context import ParseContext
from pants.base.specs import SingleAddress, Specs
from pants.build_graph.address import Address
from pants.build_graph.address_lookup_error import AddressLookupError
from pants.build_graph.app_base import AppBase, Bundle
from pants.build_graph.build_graph import BuildGraph
from pants.build_graph.remote_sources import RemoteSources
from pants.engine.addressable import BuildFileAddresses
from pants.engine.fs import PathGlobs, Snapshot, SnapshotWithMatchData
from pants.engine.legacy.structs import BaseGlobs, BundleAdaptor, BundlesField, SourcesField, TargetAdaptor
from pants.engine.rules import TaskRule, rule
from pants.engine.selectors import Get, Select
from pants.option.global_options import GlobMatchErrorBehavior
from pants.source.wrapped_globs import EagerFilesetWithSpec, FilesetRelPathWrapper
from pants.util.dirutil import fast_relpath
from pants.util.objects import Collection, SubclassesOf, datatype


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
    if not subjects:
      return

    logger.debug('Injecting specs to %s: %s', self, subjects)
    with self._resolve_context():
      specs = tuple(subjects)
      thts, = self._scheduler.product_request(TransitiveHydratedTargets,
                                              [Specs(specs)])

    self._index(thts.closure)

    for hydrated_target in thts.roots:
      yield hydrated_target.address


class HydratedTarget(datatype(['address', 'adaptor', 'dependencies'])):
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


class TransitiveHydratedTarget(datatype(['root', 'dependencies'])):
  """A recursive structure wrapping a HydratedTarget root and TransitiveHydratedTarget deps."""


class TransitiveHydratedTargets(datatype(['roots', 'closure'])):
  """A set of HydratedTarget roots, and their transitive, flattened, de-duped closure."""


class HydratedTargets(Collection.of(HydratedTarget)):
  """An intransitive set of HydratedTarget objects."""


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


def _eager_fileset_with_spec(sources_expansion, include_dirs=False):
  snapshot = sources_expansion.snapshot
  spec_path = sources_expansion.spec_path
  fds = snapshot.path_stats if include_dirs else snapshot.files
  files = tuple(fast_relpath(fd.path, spec_path) for fd in fds)

  filespec = sources_expansion.filespecs
  rel_include_globs = filespec['globs']

  if sources_expansion.glob_match_error_behavior.should_compute_matching_files():
    _warn_error_glob_expansion_failure(sources_expansion)

  relpath_adjusted_filespec = FilesetRelPathWrapper.to_filespec(rel_include_globs, spec_path)
  if filespec.has_key('exclude'):
    relpath_adjusted_filespec['exclude'] = [FilesetRelPathWrapper.to_filespec(e['globs'], spec_path)
                                            for e in filespec['exclude']]

  return EagerFilesetWithSpec(spec_path,
                              relpath_adjusted_filespec,
                              files=files,
                              files_hash=snapshot.directory_digest.fingerprint)


class SourcesGlobMatchError(Exception): pass


def _warn_error_glob_expansion_failure(sources_expansion):
  target_addr_spec = sources_expansion.target_address.spec

  kwarg_name = sources_expansion.keyword_argument_name
  base_globs = sources_expansion.base_globs
  spec_path = base_globs.spec_path
  glob_match_error_behavior = sources_expansion.glob_match_error_behavior

  match_data = sources_expansion.match_data
  if not match_data:
    raise SourcesGlobMatchError(
      "In target {spec} with {desc}={globs}: internal error: match_data must be provided."
      .format(spec=target_addr_spec, desc=kwarg_name, globs=base_globs))

  warnings = []
  for (source_pattern, source_glob) in base_globs.included_globs():
    # FIXME: need to ensure globs in output match those in input!!!!
    rel_source_glob = os.path.join(spec_path, source_glob)
    matched_result = match_data.get(rel_source_glob, None)
    if matched_result is None:
      raise SourcesGlobMatchError(
        "In target {spec} with {desc}={globs}: internal error: no match data "
        "for source glob {src}. match_data was: {match_data}."
        .format(spec=target_addr_spec, desc=kwarg_name, globs=base_globs, src=source_glob,
                match_data=match_data))
    if not matched_result:
      base_msg = "glob pattern '{}' did not match any files.".format(source_pattern)
      log_msg = (
        "In target {spec} with {desc}={globs}: {msg}"
        .format(spec=target_addr_spec, desc=kwarg_name, globs=base_globs, msg=base_msg))
      if glob_match_error_behavior.should_log_warn_on_error():
        logger.warn(log_msg)
      else:
        logger.debug(log_msg)
      warnings.append(base_msg)

  # We will raise on the first sources field with a failed path glob expansion if the option is set,
  # because we don't want to do any more fs traversals for a build that's going to fail with a
  # readable error anyway.
  if glob_match_error_behavior.should_throw_on_error(warnings):
    raise SourcesGlobMatchError(
      "In target {spec} with {desc}={globs}: Some globs failed to match "
      "and --glob-match-failure is set to {opt}. The failures were:\n{failures}"
      .format(spec=target_addr_spec, desc=kwarg_name, globs=base_globs,
              opt=glob_match_error_behavior, failures='\n'.join(warnings)))


class SourcesFieldExpansionResult(datatype([
    'spec_path',
    'target_address',
    'filespecs',
    ('base_globs', SubclassesOf(BaseGlobs)),
    ('snapshot', Snapshot),
    'match_data',
    'keyword_argument_name',
    ('glob_match_error_behavior', GlobMatchErrorBehavior),
])): pass


@rule(HydratedField, [Select(SourcesField), Select(GlobMatchErrorBehavior)])
def hydrate_sources(sources_field, glob_match_error_behavior):
  """Given a SourcesField, request a Snapshot for its path_globs and create an EagerFilesetWithSpec."""

  # TODO: should probably do this conditional in an @rule or intrinsic somewhere instead of
  # explicitly.
  # TODO: should definitely test this.
  if glob_match_error_behavior.should_compute_matching_files():
    snapshot_with_match_data = yield Get(SnapshotWithMatchData, PathGlobs, sources_field.path_globs)
    snapshot = snapshot_with_match_data.snapshot
    match_data = snapshot_with_match_data.match_data
  else:
    snapshot = yield Get(Snapshot, PathGlobs, sources_field.path_globs)
    match_data = None
  sources_expansion = SourcesFieldExpansionResult(
    spec_path=sources_field.address.spec_path,
    target_address=sources_field.address,
    filespecs=sources_field.filespecs,
    base_globs=sources_field.base_globs,
    snapshot=snapshot,
    match_data=match_data,
    keyword_argument_name='sources',
    glob_match_error_behavior=glob_match_error_behavior,
  )
  fileset_with_spec = _eager_fileset_with_spec(sources_expansion)
  yield HydratedField(sources_field.arg, fileset_with_spec)


@rule(HydratedField, [Select(BundlesField), Select(GlobMatchErrorBehavior)])
def hydrate_bundles(bundles_field, glob_match_error_behavior):
  """Given a BundlesField, request Snapshots for each of its filesets and create BundleAdaptors."""

  if glob_match_error_behavior.should_compute_matching_files():
    snapshot_matches = yield [
      Get(SnapshotWithMatchData, PathGlobs, pg) for pg in bundles_field.path_globs_list
    ]
  else:
    snapshots = yield [
      Get(Snapshot, PathGlobs, pg) for pg in bundles_field.path_globs_list
    ]
    snapshot_matches = [
      SnapshotWithMatchData(snapshot=snapshot, match_data=None) for snapshot in snapshots
    ]

  spec_path = bundles_field.address.spec_path

  bundles = []
  zipped = zip(bundles_field.bundles,
               bundles_field.filespecs_list,
               snapshot_matches)
  for bundle, filespecs, snapshot_with_match_data in zipped:
    kwargs = bundle.kwargs()
    # NB: We `include_dirs=True` because bundle filesets frequently specify directories in order
    # to trigger a (deprecated) default inclusion of their recursive contents. See the related
    # deprecation in `pants.backend.jvm.tasks.bundle_create`.
    spec_path = getattr(bundle, 'rel_path', spec_path)

    sources_expansion = SourcesFieldExpansionResult(
      spec_path=spec_path,
      target_address=bundles_field.address,
      filespecs=filespecs,
      base_globs=BaseGlobs.from_sources_field(bundle.fileset, spec_path=spec_path),
      snapshot=snapshot_with_match_data.snapshot,
      match_data=snapshot_with_match_data.match_data,
      keyword_argument_name='fileset',
      glob_match_error_behavior=glob_match_error_behavior,
    )
    kwargs['fileset'] = _eager_fileset_with_spec(sources_expansion, include_dirs=True)
    bundles.append(BundleAdaptor(**kwargs))
  yield HydratedField('bundles', bundles)


def create_legacy_graph_tasks(symbol_table):
  """Create tasks to recursively parse the legacy graph."""
  symbol_table_constraint = symbol_table.constraint()

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
    hydrate_sources,
    hydrate_bundles,
  ]
