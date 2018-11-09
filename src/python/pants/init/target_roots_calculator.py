# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import itertools
import logging
from builtins import object
from collections import defaultdict

from twitter.common.collections import OrderedSet

from pants.base.build_environment import get_buildroot, get_scm
from pants.base.cmd_line_spec_parser import CmdLineSpecParser
from pants.base.specs import DescendantAddresses, SingleAddress, Specs
from pants.base.target_roots import TargetRoots
from pants.build_graph.address import Address
from pants.engine.legacy.graph import TransitiveHydratedTargets, target_types_from_symbol_table
from pants.engine.legacy.source_mapper import EngineSourceMapper
from pants.goal.workspace import ScmWorkspace
from pants.scm.subsystems.changed import ChangedRequest


logger = logging.getLogger(__name__)


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
  def from_iterable(cls, target_types, adaptor_iter):
    """Create a new DependentGraph from an iterable of TargetAdaptor subclasses."""
    inst = cls(target_types)
    for target_adaptor in adaptor_iter:
      inst.inject_target(target_adaptor)
    return inst

  def __init__(self, target_types):
    self._dependent_address_map = defaultdict(set)
    self._target_types = target_types

  def inject_target(self, target_adaptor):
    """Inject a target, respecting all sources of dependencies."""
    target_cls = self._target_types[target_adaptor.type_alias]

    declared_deps = target_adaptor.dependencies
    implicit_deps = (Address.parse(s)
                     for s in target_cls.compute_dependency_specs(kwargs=target_adaptor.kwargs()))

    for dep in itertools.chain(declared_deps, implicit_deps):
      self._dependent_address_map[dep].add(target_adaptor.address)

  def dependents_of_addresses(self, addresses):
    """Given an iterable of addresses, yield all of those addresses dependents."""
    seen = set(addresses)
    for address in addresses:
      for dependent_address in self._dependent_address_map[address]:
        if dependent_address not in seen:
          seen.add(dependent_address)
          yield dependent_address

  def transitive_dependents_of_addresses(self, addresses):
    """Given an iterable of addresses, yield all of those addresses dependents, transitively."""
    addresses_to_visit = set(addresses)
    while 1:
      dependents = set(self.dependents_of_addresses(addresses))
      # If we've exhausted all dependencies or visited all remaining nodes, break.
      if (not dependents) or dependents.issubset(addresses_to_visit):
        break
      addresses = dependents.difference(addresses_to_visit)
      addresses_to_visit.update(dependents)

    transitive_set = itertools.chain(
      *(self._dependent_address_map[address] for address in addresses_to_visit)
    )
    for dep in transitive_set:
      yield dep


class InvalidSpecConstraint(Exception):
  """Raised when invalid constraints are given via target specs and arguments like --changed*."""


class TargetRootsCalculator(object):
  """Determines the target roots for a given pants run."""

  @classmethod
  def parse_specs(cls, target_specs, build_root=None, exclude_patterns=None, tags=None):
    """Parse string specs into unique `Spec` objects.

    :param iterable target_specs: An iterable of string specs.
    :param string build_root: The path to the build root.
    :returns: An `OrderedSet` of `Spec` objects.
    """
    build_root = build_root or get_buildroot()
    spec_parser = CmdLineSpecParser(build_root)

    dependencies = tuple(OrderedSet(spec_parser.parse_spec(spec_str) for spec_str in target_specs))
    if not dependencies:
      return None
    return [Specs(
      dependencies=dependencies,
      exclude_patterns=exclude_patterns if exclude_patterns else tuple(),
      tags=tags)
    ]

  @classmethod
  def create(cls, options, session, symbol_table, build_root=None, exclude_patterns=None, tags=None):
    """
    :param Options options: An `Options` instance to use.
    :param session: The Scheduler session
    :param symbol_table: The symbol table
    :param string build_root: The build root.
    """
    # Determine the literal target roots.
    spec_roots = cls.parse_specs(
      target_specs=options.target_specs,
      build_root=build_root,
      exclude_patterns=exclude_patterns,
      tags=tags)

    # Determine `Changed` arguments directly from options to support pre-`Subsystem`
    # initialization paths.
    changed_options = options.for_scope('changed')
    changed_request = ChangedRequest.from_options(changed_options)

    # Determine the `--owner-of=` arguments provided from the global options
    owned_files = options.for_global_scope().owner_of

    logger.debug('spec_roots are: %s', spec_roots)
    logger.debug('changed_request is: %s', changed_request)
    logger.debug('owned_files are: %s', owned_files)
    scm = get_scm()
    change_calculator = ChangeCalculator(scheduler=session, symbol_table=symbol_table, scm=scm) if scm else None
    owner_calculator = OwnerCalculator(scheduler=session, symbol_table=symbol_table) if owned_files else None
    targets_specified = sum(1 for item
                         in (changed_request.is_actionable(), owned_files, spec_roots)
                         if item)

    if targets_specified > 1:
      # We've been provided a more than one of: a change request, an owner request, or spec roots.
      raise InvalidSpecConstraint(
        'Multiple target selection methods provided. Please use only one of '
        '--changed-*, --owner-of, or target specs'
      )

    if change_calculator and changed_request.is_actionable():
      # We've been provided no spec roots (e.g. `./pants list`) AND a changed request. Compute
      # alternate target roots.
      changed_addresses = change_calculator.changed_target_addresses(changed_request)
      logger.debug('changed addresses: %s', changed_addresses)
      dependencies = tuple(SingleAddress(a.spec_path, a.target_name) for a in changed_addresses)
      return TargetRoots([Specs(dependencies=dependencies, exclude_patterns=exclude_patterns, tags=tags)])

    if owner_calculator and owned_files:
      # We've been provided no spec roots (e.g. `./pants list`) AND a owner request. Compute
      # alternate target roots.
      owner_addresses = owner_calculator.owner_target_addresses(owned_files)
      logger.debug('owner addresses: %s', owner_addresses)
      dependencies = tuple(SingleAddress(a.spec_path, a.target_name) for a in owner_addresses)
      return TargetRoots([Specs(dependencies=dependencies, exclude_patterns=exclude_patterns, tags=tags)])

    return TargetRoots(spec_roots)


class ChangeCalculator(object):
  """A ChangeCalculator that finds the target addresses of changed files based on scm."""

  def __init__(self, scheduler, symbol_table, scm, workspace=None, changes_since=None,
               diffspec=None):
    """
    :param scheduler: The `Scheduler` instance to use for computing file to target mappings.
    :param symbol_table: The symbol table.
    :param scm: The `Scm` instance to use for change determination.
    """
    self._scm = scm or get_scm()
    self._scheduler = scheduler
    self._symbol_table = symbol_table
    self._mapper = EngineSourceMapper(self._scheduler)
    self._workspace = workspace or ScmWorkspace(scm)
    self._changes_since = changes_since
    self._diffspec = diffspec

  def changed_files(self, changes_since=None, diffspec=None):
    """Determines the files changed according to SCM/workspace and options."""
    diffspec = diffspec or self._diffspec
    if diffspec:
      return self._workspace.changes_in(diffspec)

    changes_since = changes_since or self._changes_since or self._scm.current_rev_identifier()
    return self._workspace.touched_files(changes_since)

  def iter_changed_target_addresses(self, changed_request):
    """Given a `ChangedRequest`, compute and yield all affected target addresses."""
    changed_files = self.changed_files(changed_request.changes_since, changed_request.diffspec)
    logger.debug('changed files: %s', changed_files)
    if not changed_files:
      return

    changed_addresses = set(address
                            for address
                            in self._mapper.iter_target_addresses_for_sources(changed_files))
    for address in changed_addresses:
      yield address

    if changed_request.include_dependees not in ('direct', 'transitive'):
      return

    # TODO: For dependee finding, we technically only need to parse all build files to collect target
    # dependencies. But in order to fully validate the graph and account for the fact that deleted
    # targets do not show up as changed roots, we use the `TransitiveHydratedTargets` product.
    #   see https://github.com/pantsbuild/pants/issues/382
    specs = (DescendantAddresses(''),)
    adaptor_iter = (t.adaptor
                    for targets in self._scheduler.product_request(TransitiveHydratedTargets,
                                                                   [Specs(specs)])
                    for t in targets.roots)
    graph = _DependentGraph.from_iterable(target_types_from_symbol_table(self._symbol_table),
                                          adaptor_iter)

    if changed_request.include_dependees == 'direct':
      for address in graph.dependents_of_addresses(changed_addresses):
        yield address
    elif changed_request.include_dependees == 'transitive':
      for address in graph.transitive_dependents_of_addresses(changed_addresses):
        yield address

  def changed_target_addresses(self, changed_request):
    return list(self.iter_changed_target_addresses(changed_request))


class OwnerCalculator(object):
  """An OwnerCalculator that finds the target addresses of the files passed down as arguments
  to --owner-of
  """

  def __init__(self, scheduler, symbol_table):
    """
    :param scheduler: The `Scheduler` instance to use for computing file to target mapping
    :param symbol_table: The symbol table.
    """
    self._scheduler = scheduler
    self._symbol_table = symbol_table
    self._mapper = EngineSourceMapper(self._scheduler)

  def iter_owner_target_addresses(self, owned_files):
    """Given an list of owned files, compute and yield all affected target addresses"""
    owner_addresses = set(address
                          for address
                          in self._mapper.iter_target_addresses_for_sources(owned_files))
    for address in owner_addresses:
      yield address

  def owner_target_addresses(self, owner_request):
    return list(self.iter_owner_target_addresses(owner_request))
