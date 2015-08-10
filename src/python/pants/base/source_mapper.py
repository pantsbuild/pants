# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.base.build_environment import get_buildroot


class SourceMapper(object):
  """A utility for making a best-effort mapping of source files to targets that own them.

  This attempts to avoid loading more than needed by lazily searching for and loading BUILD files
  adjacent to or in parent directories (up to the buildroot) of a source to construct a (partial)
  mapping of sources to owning targets.

  If in stop-after-match mode, a search will not traverse into parent directories once an owner
  is identified. THIS MAY FAIL TO FIND ADDITIONAL OWNERS in parent directories, or only find them
  when other sources are also mapped first, which cause those owners to be loaded. Some repositories
  may be able to use this to avoid expensive walks, but others may need to prefer correctness.
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

  def target_addresses_for_source(self, source):
    """Searches for BUILD files adjacent or above a source in the file hierarchy.
    - Walks up the directory tree until it reaches a previously searched path.
    - Stops after looking in the buildroot.

    :param str source: The source at which to start the search.
    """

    result = []

    root = get_buildroot()
    path = os.path.dirname(source)

    # a top-level source has empty dirname, so do/while instead of straight while loop.
    walking = True
    while walking:
      candidate = self._address_mapper.from_cache(root_dir=root, relpath=path, must_exist=False)
      if candidate.file_exists():
        result.extend(list(self.find_target_for_source(source, candidate.family())))

      if self._stop_after_match and len(result) > 0:
        break
      walking = bool(path)
      path = os.path.dirname(path)

    return result

  def find_target_for_source(self, source, build_files):
    for build_file in build_files:
      address_map = self._address_mapper._address_map_from_spec_path(build_file.spec_path)
      for address, addressable in address_map.values():
        self._build_graph.inject_address_closure(address)
        target = self._build_graph._target_addressable_to_target(address, addressable)
        sources = target.payload.get_field('sources')
        if sources and sources.matches(source):
          yield address
        if address.build_file.relpath == source:
          yield address
        if target.has_resources:
          for resource in target.resources:
            """
            :type resource: pants.backend.core.targets.resources.Resources
            """
            if resource.payload.sources.matches(source):
              yield address
