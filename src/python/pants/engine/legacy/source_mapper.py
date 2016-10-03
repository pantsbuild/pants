# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.base.specs import AscendantAddresses, SingleAddress
from pants.build_graph.address import parse_spec
from pants.build_graph.source_mapper import SourceMapper
from pants.engine.legacy.address_mapper import LegacyAddressMapper
from pants.engine.legacy.graph import LegacyTarget
from pants.source.wrapped_globs import EagerFilesetWithSpec


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

  def __init__(self, engine):
    self._engine = engine

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

  def _iter_owned_files_from_legacy_target(self, legacy_target):
    """Given a `LegacyTarget` instance, yield all files owned by the target."""
    target_kwargs = legacy_target.adaptor.kwargs()

    # Handle targets like `python_binary` which have a singular `source='main.py'` declaration.
    target_source = target_kwargs.get('source')
    if target_source:
      yield os.path.join(legacy_target.adaptor.address.spec_path, target_source)

    # Handle `sources`-declaring targets.
    target_sources = target_kwargs.get('sources', [])
    if target_sources:
      for f in target_sources.iter_relative_paths():
        yield f

    # Handle `resources`-declaring targets.
    target_resources = target_kwargs.get('resources')
    if target_resources:
      # N.B. `resources` params come in two flavors:
      #
      # 1) Strings of filenames, which are represented in kwargs by an EagerFilesetWithSpec e.g.:
      #
      #      python_library(..., resources=['file.txt', 'file2.txt'])
      #
      if isinstance(target_resources, EagerFilesetWithSpec):
        for f in target_resources.iter_relative_paths():
          yield f
      # 2) Strings of addresses, which are represented in kwargs by a list of strings:
      #
      #      java_library(..., resources=['testprojects/src/resources/...:resource'])
      #
      #    which is closer in premise to the `resource_targets` param.
      else:
        resource_dep_subjects = resolve_and_parse_specs(legacy_target.adaptor.address.spec_path,
                                                        target_resources)
        # Fetch `LegacyTarget` products for all of the resources.
        for resource_target in self._engine.product_request(LegacyTarget, resource_dep_subjects):
          resource_sources = resource_target.adaptor.kwargs().get('sources')
          if resource_sources:
            for f in resource_sources.iter_relative_paths():
              yield f

  def iter_target_addresses_for_sources(self, sources):
    """Bulk, iterable form of `target_addresses_for_source`."""
    # Walk up the buildroot looking for targets that would conceivably claim changed sources.
    sources_set = set(sources)
    subjects = [AscendantAddresses(directory=d) for d in self._unique_dirs_for_sources(sources_set)]

    for legacy_target in self._engine.product_request(LegacyTarget, subjects):
      legacy_address = legacy_target.adaptor.address

      # Handle BUILD files.
      if any(LegacyAddressMapper.is_declaring_file(legacy_address, f) for f in sources_set):
        yield legacy_address
      else:
        # Handle claimed files.
        target_files_iter = self._iter_owned_files_from_legacy_target(legacy_target)
        if any(source_file in sources_set for source_file in target_files_iter):
          # At least one file in this targets sources match our changed sources - emit its address.
          yield legacy_address
