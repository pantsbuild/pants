# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.base.build_environment import get_buildroot
from pants.base.cmd_line_spec_parser import CmdLineSpecParser
from pants.base.specs import AscendantAddresses
from pants.build_graph.source_mapper import SourceMapper
from pants.engine.legacy.address_mapper import LegacyAddressMapper
from pants.engine.legacy.graph import LegacyTarget
from pants.source.wrapped_globs import EagerFilesetWithSpec


class EngineSourceMapper(SourceMapper):
  """A v2 engine backed SourceMapper that supports pre-`BuildGraph` cache warming in the daemon."""

  def __init__(self, engine, spec_parser=None):
    self._engine = engine
    self._spec_parser = spec_parser or CmdLineSpecParser(get_buildroot())

  def _unique_dirs_for_sources(self, sources):
    """Given an iterable of sources, yield unique dirname'd paths."""
    seen = set()
    for source in sources:
      source_dir = os.path.dirname(source)
      if source_dir not in seen:
        seen.add(source_dir)
        yield source_dir

  def target_addresses_for_source(self, source):
    return list(self.iter_target_addresses_for_sources, [source])

  def _parse_specs(self, rel_path, specs):
    """Given a relative path and set of input specs, produce a list of absolute specs."""
    for spec in specs:
      if spec.startswith(':'):
        yield self._spec_parser.parse_spec(''.join((rel_path, spec)))
      else:
        yield self._spec_parser.parse_spec(spec)

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
      # Use the iterative functionality of `EagerFilesetWithSpec`.
      for f in target_sources:
        yield os.path.join(target_sources.rel_root, f)

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
        for f in target_resources:
          yield os.path.join(target_resources.rel_root, f)
      # 2) Strings of addresses, which are represented in kwargs by a list of strings:
      #
      #      java_library(..., resources=['testprojects/src/resources/...:resource'])
      #
      #    which is closer in premise to the `resource_targets` param.
      else:
        resource_dep_subjects = list(self._parse_specs(legacy_target.adaptor.address.spec_path,
                                                       target_resources))
        # Fetch `LegacyTarget` products for all of the resources.
        for resource_target in self._engine.product_request(LegacyTarget, resource_dep_subjects):
          resource_sources = resource_target.adaptor.kwargs().get('sources')
          if resource_sources:
            for f in resource_sources:
              yield os.path.join(resource_sources.rel_root, f)

  def iter_target_addresses_for_sources(self, sources):
    """Bulk, iterable form of `target_addresses_for_source`."""
    # Walk up the buildroot looking for targets that would conceivably claim changed sources.
    subjects = [AscendantAddresses(directory=d) for d in self._unique_dirs_for_sources(sources)]
    sources_set = set(sources)

    for legacy_target in self._engine.product_request(LegacyTarget, subjects):
      legacy_address = legacy_target.adaptor.address

      # Handle BUILD files.
      if any(LegacyAddressMapper.is_declaring_file(legacy_address, f) for f in sources_set):
        yield legacy_address
      else:
        # Handle claimed files.
        target_files_iter = self._iter_owned_files_from_legacy_target(legacy_target)
        if any(True for source_file in target_files_iter if source_file in sources_set):
          # At least one file in this targets sources match our changed sources - emit its address.
          yield legacy_address
