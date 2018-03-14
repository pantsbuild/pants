# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

import six

from pants.base.specs import AscendantAddresses, SingleAddress
from pants.build_graph.address import parse_spec
from pants.build_graph.source_mapper import SourceMapper
from pants.engine.legacy.address_mapper import LegacyAddressMapper
from pants.engine.legacy.graph import HydratedTargets
from pants.source.filespec import any_matches_filespec


def iter_resolve_and_parse_specs(rel_path, specs):
  """Given a relative path and set of input specs, produce a list of proper `Spec` objects.

  :param string rel_path: The relative path to the input specs from the build root.
  :param iterable specs: An iterable of specs.
  """
  for spec in specs:
    spec_path, target_name = parse_spec(spec, rel_path)
    yield SingleAddress(spec_path, target_name)


def resolve_and_parse_specs(*args, **kwargs):
  return list(iter_resolve_and_parse_specs(*args, **kwargs))


class EngineSourceMapper(SourceMapper):
  """A v2 engine backed SourceMapper that supports pre-`BuildGraph` cache warming in the daemon."""

  def __init__(self, scheduler):
    self._scheduler = scheduler

  def _unique_dirs_for_sources(self, sources):
    """Given an iterable of sources, yield unique dirname'd paths."""
    seen = set()
    for source in sources:
      source_dir = os.path.dirname(source)
      if source_dir not in seen:
        seen.add(source_dir)
        yield source_dir

  def target_addresses_for_source(self, source):
    return list(self.iter_target_addresses_for_sources([source]))

  def _match_sources(self, sources_set, fileset):
    # NB: Deleted files can only be matched against the 'filespec' (ie, `PathGlobs`) for a target,
    # so we don't actually call `fileset.matches` here.
    # TODO: This call should be pushed down into the engine to match directly against
    # `PathGlobs` as we erode the `AddressMapper`/`SourceMapper` split.
    return any_matches_filespec(sources_set, fileset.filespec)

  def _owns_any_source(self, sources_set, legacy_target):
    """Given a `HydratedTarget` instance, check if it owns the given source file."""
    target_kwargs = legacy_target.adaptor.kwargs()

    # Handle targets like `python_binary` which have a singular `source='main.py'` declaration.
    target_source = target_kwargs.get('source')
    if target_source:
      path_from_build_root = os.path.join(legacy_target.adaptor.address.spec_path, target_source)
      if path_from_build_root in sources_set:
        return True

    # Handle `sources`-declaring targets.
    target_sources = target_kwargs.get('sources', [])
    if target_sources and self._match_sources(sources_set, target_sources):
      return True

    return False

  def iter_target_addresses_for_sources(self, sources):
    """Bulk, iterable form of `target_addresses_for_source`."""
    # Walk up the buildroot looking for targets that would conceivably claim changed sources.
    sources_set = set(sources)
    subjects = [AscendantAddresses(directory=d) for d in self._unique_dirs_for_sources(sources_set)]

    # Uniqify all transitive hydrated targets.
    hydrated_target_to_address = {}
    for hydrated_targets in self._scheduler.product_request(HydratedTargets, subjects):
      for hydrated_target in hydrated_targets.dependencies:
        if hydrated_target not in hydrated_target_to_address:
          hydrated_target_to_address[hydrated_target] = hydrated_target.adaptor.address

    for hydrated_target, legacy_address in six.iteritems(hydrated_target_to_address):
      # Handle BUILD files.
      if (LegacyAddressMapper.any_is_declaring_file(legacy_address, sources_set) or
          self._owns_any_source(sources_set, hydrated_target)):
        yield legacy_address
