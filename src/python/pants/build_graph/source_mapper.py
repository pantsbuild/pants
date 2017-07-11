# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from collections import defaultdict

from pants.build_graph.build_file_address_mapper import BuildFileAddressMapper


class SourceMapper(object):
  """A utility for making a mapping of source files to targets that own them."""

  def target_addresses_for_source(self, source):
    raise NotImplementedError


class SpecSourceMapper(SourceMapper):
  """
  Uses sources specs to identify an owner target of a source.

  Note: it doesn't check if a file exists.
  """

  def __init__(self, address_mapper, build_graph, stop_after_match=False):
    """
    :param AddressMapper address_mapper: An address mapper that can be used to populate the
      `build_graph` with targets source mappings are needed for.
    :param BuildGraph build_graph: The build graph to map sources from.
    :param bool stop_after_match: If `True` a search will not traverse into parent directories once
      an owner is identified.
    """
    self._stop_after_match = stop_after_match
    self._build_graph = build_graph
    self._address_mapper = address_mapper

  def target_addresses_for_source(self, source):
    result = []
    path = source

    # a top-level source has empty dirname, so do/while instead of straight while loop.
    while path:
      path = os.path.dirname(path)
      try:
        result.extend(self._find_targets_for_source(source, path))
      except BuildFileAddressMapper.BuildFileScanError:
        pass
      if self._stop_after_match and len(result) > 0:
        break

    return result

  def _find_targets_for_source(self, source, spec_path):
    for address in self._address_mapper.addresses_in_spec_path(spec_path):
      self._build_graph.inject_address_closure(address)
      target = self._build_graph.get_target(address)
      sources_field = target.payload.get_field('sources')
      if sources_field and sources_field.matches(source):
        yield address
      elif self._address_mapper.is_declaring_file(address, source):
        yield address
      elif target.has_resources:
        for resource in target.resources:
          """
          :type resource: pants.build_graph.resources.Resources
          """
          if resource.payload.sources.matches(source):
            yield address
            break


class LazySourceMapper(SourceMapper):
  """
  This attempts to avoid loading more than needed by lazily searching for and loading BUILD files
  adjacent to or in parent directories (up to the buildroot) of a source to construct a (partial)
  mapping of sources to owning targets.

  If in stop-after-match mode, a search will not traverse into parent directories once an owner
  is identified. THIS MAY FAIL TO FIND ADDITIONAL OWNERS in parent directories, or only find them
  when other sources are also mapped first, which cause those owners to be loaded. Some repositories
  may be able to use this to avoid expensive walks, but others may need to prefer correctness.

  A LazySourceMapper reuses computed mappings and only searches a given path once as
  populating the BuildGraph is expensive, so in general there should only be one instance of it.
  """

  def __init__(self, address_mapper, build_graph, stop_after_match=False):
    """Initialize LazySourceMapper.

    :param AddressMapper address_mapper: An address mapper that can be used to populate the
      `build_graph` with targets source mappings are needed for.
    :param BuildGraph build_graph: The build graph to map sources from.
    :param bool stop_after_match: If `True` a search will not traverse into parent directories once
      an owner is identified.
    """
    self._stop_after_match = stop_after_match
    self._build_graph = build_graph
    self._address_mapper = address_mapper
    self._source_to_address = defaultdict(set)
    self._mapped_paths = set()
    self._searched_sources = set()

  def _find_owners(self, source):
    """Searches for BUILD files adjacent or above a source in the file hierarchy.
    - Walks up the directory tree until it reaches a previously searched path.
    - Stops after looking in the buildroot.

    If self._stop_after_match is set, stops searching once a source is mapped, even if the parent
    has yet to be searched. See class docstring for discussion.

    :param str source: The source at which to start the search.
    """
    # Bail instantly if a source has already been searched
    if source in self._searched_sources:
      return
    self._searched_sources.add(source)

    path = os.path.dirname(source)

    # a top-level source has empty dirname, so do/while instead of straight while loop.
    walking = True
    while walking:
      # It is possible
      if path not in self._mapped_paths:
        try:
          self._map_sources_from_spec_path(path)
        except BuildFileAddressMapper.BuildFileScanError:
          pass
        self._mapped_paths.add(path)
      elif not self._stop_after_match:
        # If not in stop-after-match mode, once a path is seen visited, all parents can be assumed.
        return

      # See class docstring
      if self._stop_after_match and source in self._source_to_address:
        return

      walking = bool(path)
      path = os.path.dirname(path)

  def _map_sources_from_spec_path(self, spec_path):
    """Populate mapping of source to owning addresses with targets from given BUILD files.

    :param spec_path: a spec_path of targets from which to map sources.
    """
    for address in self._address_mapper.addresses_in_spec_path(spec_path):
      self._build_graph.inject_address_closure(address)
      target = self._build_graph.get_target(address)
      if target.has_resources:
        for resource in target.resources:
          for item in resource.sources_relative_to_buildroot():
            self._source_to_address[item].add(address)

      for target_source in target.sources_relative_to_buildroot():
        self._source_to_address[target_source].add(address)
      if not target.is_synthetic:
        self._source_to_address[address.rel_path].add(address)

  def target_addresses_for_source(self, source):
    """Attempt to find targets which own a source by searching up directory structure to buildroot.

    :param string source: The source to look up.
    """
    self._find_owners(source)
    return self._source_to_address[source]
