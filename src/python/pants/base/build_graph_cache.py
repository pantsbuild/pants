# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import threading

from pants.base.address_lookup_error import AddressLookupError
from pants.base.build_file_address_mapper import BuildFileAddressMapper
from pants.base.build_file_parser import BuildFileParser
from pants.base.build_graph import BuildGraph


class BuildGraphCache(object):
  """A facade that simplifies BUILD file parsing and BuildGraph operations for caching."""

  @classmethod
  def create(cls, root_dir, build_config, build_file_type):
    build_file_parser = BuildFileParser(build_config, root_dir)
    address_mapper = BuildFileAddressMapper(build_file_parser, build_file_type)
    build_graph = BuildGraph(address_mapper)

    return BuildGraphCache(root_dir, build_file_type, address_mapper, build_graph)

  def __init__(self, root_dir, build_file_type, address_mapper, build_graph):
    self._root_dir = root_dir
    self._build_file_type = build_file_type
    self._address_mapper = address_mapper
    self._build_graph = build_graph

    self._logger = logging.getLogger(__name__)
    self._lock = threading.RLock()

    # TODO: if we can fully encapsulate all things below, we can use this base facade in GoalRunner too
    # self._spec_parser = CmdLineSpecParser(
    #   self._root_dir,
    #   self._address_mapper,
    #   spec_excludes=self._spec_excludes,
    #   exclude_target_regexps=self._global_options.exclude_target_regexp
    # )
    # TODO: encapsulate BuildConfiguration in this
    # TODO: encapsulate build_file_type in this

  def _spec_path_to_addresses(self, spec_path, raise_on_error=False):
    """Parse a BUILD file into a set of addresses that we can inject into the BuildGraph."""
    try:
      # Here we rely on the fact that the spec path for a given BUILD is exactly its relative path.
      return self._address_mapper.addresses_in_spec_path(spec_path)
    except AddressLookupError as e:
      self._logger.debug('caught AddressLookupError({})'.format(e))
      if not raise_on_error: raise

# def _requirements_to_addresses(self, requirements_file, raise_on_error=False):
#   """Parse a requirements.txt into a set of addresses that we can inject into the BuildGraph."""
#   # The mapping here is /path/to/requirements.txt -> /path/to (which nets /path/to/BUILD:).
#   requirements_spec = os.path.dirname(requirements_file)
#   return self._build_file_path_to_addresses(requirements_spec, raise_on_error=raise_on_error)

  def _reinsert_addresses_to_build_graph(self, addresses):
    """Inject a set of address closures into the BuildGraph."""
    for address in addresses:
      self._logger.debug('ingesting address: {}'.format(address))
      try:
        self._build_graph.inject_address_closure(address)
      except self._address_mapper.AddressNotInBuildFile:
        # TODO
        raise

  def reparse_build_file(self, build_file):
    """
    :param build_file: The build file to parse.
    :type build_file: :class:`pants.base.build_file.BuildFile`
    """

    # Destroy cached content of the build file.
    self._build_file_type.invalidate_cache_entry(build_file.root_dir, build_file.spec_path, True)
    # Destroy cached spec->addressmap mapping.
    self._address_mapper.invalidate_address_map_entry(build_file.spec_path)

    # Remove targets previously defined by the build file in question.
    with self._lock:
      self._build_graph.remove_targets_by_spec_path(build_file.spec_path)

    # Since the cache entries are invalidated, the build file will be re-parsed.
    addresses = self._spec_path_to_addresses(build_file.spec_path)

    # Insert targets now defined in the build file.
    with self._lock:
      self._reinsert_addresses_to_build_graph(addresses)

# Unsupported yet.
# def ingest_requirements_file(self, build_file):
#   addresses = self._requirements_to_addresses(build_file)
#   self._update_addresses(addresses)
