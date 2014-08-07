# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from collections import defaultdict
import logging
import traceback
import sys

from twitter.common.lang import Compatibility

from pants.base.address import BuildFileAddress, parse_spec, SyntheticAddress
from pants.base.build_environment import get_buildroot
from pants.base.build_file import BuildFile
from pants.base.build_graph import BuildGraph


logger = logging.getLogger(__name__)


class BuildFileCache(object):
  """A little cache for BuildFiles.
  They are mildly expensive to construct since they actually peek
  at the filesystem in their __init__.  This adds up when translating specs to addresses.
  """

  _spec_path_to_build_file_cache = {}

  @classmethod
  def spec_path_to_build_file(cls, root_dir, spec_path):
    if (root_dir, spec_path) not in cls._spec_path_to_build_file_cache:
      cls._spec_path_to_build_file_cache[(root_dir, spec_path)] = BuildFile(root_dir, spec_path)
    return cls._spec_path_to_build_file_cache[(root_dir, spec_path)]

  @classmethod
  def clear(cls):
    cls._spec_path_to_build_file_cache = {}


class BuildFileParser(object):
  """Parses BUILD files for a given repo build configuration."""

  class TargetConflictException(Exception):
    """Thrown if the same target is redefined in a BUILD file"""

  class SiblingConflictException(Exception):
    """Thrown if the same target is redefined in another BUILD file in the same directory"""

  class InvalidTargetException(Exception):
    """Thrown if the user called for a target not present in a BUILD file."""

  class EmptyBuildFileException(Exception):
    """Thrown if the user called for a target when none are present in a BUILD file."""

  def __init__(self, build_configuration, root_dir, run_tracker=None):
    self._build_configuration = build_configuration
    self._root_dir = root_dir
    self.run_tracker = run_tracker

    self._target_proxy_by_address = {}
    self._target_proxies_by_build_file = defaultdict(set)
    self._added_build_files = set()
    self._added_build_file_families = set()

    self.addresses_by_build_file = defaultdict(set)

  def registered_aliases(self):
    """Returns a copy of the registered build file aliases this build file parser uses."""
    return self._build_configuration.registered_aliases()

  def inject_address_into_build_graph(self, address, build_graph):
    self._populate_target_proxy_for_address(address)
    target_proxy = self._target_proxy_by_address[address]

    if not build_graph.contains_address(address):
      target = target_proxy.to_target(build_graph)
      build_graph.inject_target(target)

  def parse_spec(self, spec, relative_to=None, context=None):
    try:
      return parse_spec(spec, relative_to=relative_to)
    except ValueError as e:
      if context:
        msg = ('Invalid spec {spec} found while '
               'parsing {context}: {exc}').format(spec=spec, context=context, exc=e)
      else:
        msg = 'Invalid spec {spec}: {exc}'.format(spec=spec, exc=e)
      raise self.InvalidTargetException(msg)

  def inject_address_closure_into_build_graph(self,
                                              address,
                                              build_graph,
                                              addresses_already_closed=None):
    addresses_already_closed = addresses_already_closed or set()

    if address in addresses_already_closed:
      return

    self._populate_target_proxy_transitive_closure_for_address(address)

    target_proxy = self._target_proxy_by_address[address]

    if not build_graph.contains_address(address):
      addresses_already_closed.add(address)
      dep_addresses = target_proxy.dependency_addresses(BuildFileCache.spec_path_to_build_file)
      for dep_address in dep_addresses:
        self.inject_address_closure_into_build_graph(dep_address,
                                                     build_graph,
                                                     addresses_already_closed)
      target = target_proxy.to_target(build_graph)
      build_graph.inject_target(target, dependencies=dep_addresses)

      for traversable_spec in target.traversable_dependency_specs:
        spec_path, target_name = self.parse_spec(traversable_spec,
                                                 relative_to=address.spec_path,
                                                 context='dependencies of {0}'.format(address))
        self._inject_spec_closure_into_build_graph(spec_path,
                                                   target_name,
                                                   build_graph,
                                                   addresses_already_closed)
        traversable_spec_target = build_graph.get_target(SyntheticAddress(spec_path, target_name))
        if traversable_spec_target not in target.dependencies:
          build_graph.inject_dependency(dependent=target.address,
                                        dependency=traversable_spec_target.address)
          target.mark_transitive_invalidation_hash_dirty()

      for traversable_spec in target.traversable_specs:
        spec_path, target_name = self.parse_spec(traversable_spec,
                                                 relative_to=address.spec_path,
                                                 context='traversable specs of {0}'.format(address))
        self._inject_spec_closure_into_build_graph(spec_path,
                                                   target_name,
                                                   build_graph,
                                                   addresses_already_closed)
        target.mark_transitive_invalidation_hash_dirty()

  def inject_spec_closure_into_build_graph(self, spec, build_graph, addresses_already_closed=None):
    spec_path, target_name = self.parse_spec(spec)
    self._inject_spec_closure_into_build_graph(spec_path,
                                               target_name,
                                               build_graph,
                                               addresses_already_closed)

  def _inject_spec_closure_into_build_graph(self,
                                            spec_path,
                                            target_name,
                                            build_graph,
                                            addresses_already_closed=None):
    addresses_already_closed = addresses_already_closed or set()
    build_file = BuildFileCache.spec_path_to_build_file(self._root_dir, spec_path)
    address = BuildFileAddress(build_file, target_name)
    self.inject_address_closure_into_build_graph(address, build_graph, addresses_already_closed)

  def _populate_target_proxy_for_address(self, address):
    self.parse_build_file_family(address.build_file)

    if address not in self._target_proxy_by_address:
      raise ValueError('{address} from spec {spec} was not found in BUILD file {build_file}.'
                       .format(address=address,
                               spec=address.spec,
                               build_file=address.build_file))

  def _raise_incorrect_target_error(self, wrong_target, targets):
    """Search through the list of targets and return those which originate from the same folder
    which wrong_target resides in.

    :raises: A helpful error message listing possible correct target addresses.
    """
    def path_parts(build):  # Gets a tuple of directory, filename.
        build = str(build)
        slash = build.rfind('/')
        if slash < 0:
          return '', build
        return build[:slash], build[slash+1:]

    def are_siblings(a, b):  # Are the targets in the same directory?
      return path_parts(a)[0] == path_parts(b)[0]

    valid_specs = []
    all_same = True
    # Iterate through all addresses, saving those which are similar to the wrong address.
    for target in targets:
      if are_siblings(target.build_file, wrong_target.build_file):
        possibility = (path_parts(target.build_file)[1], target.spec[target.spec.rfind(':'):])
        # Keep track of whether there are multiple BUILD files or just one.
        if all_same and valid_specs and possibility[0] != valid_specs[0][0]:
          all_same = False
        valid_specs.append(possibility)

    # Trim out BUILD extensions if there's only one anyway; no need to be redundant.
    if all_same:
      valid_specs = [('', tail) for head, tail in valid_specs]
    # Might be neat to sort by edit distance or something, but for now alphabetical is fine.
    valid_specs = [''.join(pair) for pair in sorted(valid_specs)]

    # Give different error messages depending on whether BUILD file was empty.
    if valid_specs:
      one_of = ' one of' if len(valid_specs) > 1 else '' # Handle plurality, just for UX.
      raise self.InvalidTargetException((
          ':{address} from spec {spec} was not found in BUILD file {build_file}. Perhaps you '
          'meant{one_of}: \n  {specs}').format(address=wrong_target.target_name,
                                               spec=wrong_target.spec,
                                               build_file=wrong_target.build_file,
                                               one_of=one_of,
                                               specs='\n  '.join(valid_specs)))
    # There were no targets in the BUILD file.
    raise self.EmptyBuildFileException((
        ':{address} from spec {spec} was not found in BUILD file {build_file}, because that '
        'BUILD file contains no targets.').format(address=wrong_target.target_name,
                                                  spec=wrong_target.spec,
                                                  build_file=wrong_target.build_file))

  def _populate_target_proxy_transitive_closure_for_address(self,
                                                            address,
                                                            addresses_already_closed=None):
    """Recursively parse the BUILD files transitively referred to by `address`.
    Note that `address` must be a BuildFileAddress, not a SyntheticAddress.
    From each parsed BUILD file, TargetProxy objects are generated.  For the TargetProxies
    that are dependencies of the root address to close over, recursively parse their dependency
    addresses.
    This method is immune to cycles between either BUILD files or individual Targets, but it is
    also incapable of detecting them.
    """

    addresses_already_closed = addresses_already_closed or set()

    if address in addresses_already_closed:
      return

    self.parse_build_file_family(address.build_file)

    if address not in self._target_proxy_by_address: # Raise helpful error message.
      self._raise_incorrect_target_error(address, self._target_proxy_by_address.keys())

    target_proxy = self._target_proxy_by_address[address]
    addresses_already_closed.add(address)

    try:
      for dep_address in target_proxy.dependency_addresses(BuildFileCache.spec_path_to_build_file):
        if dep_address not in addresses_already_closed:
          self._populate_target_proxy_transitive_closure_for_address(dep_address,
                                                                   addresses_already_closed)
    except BuildFile.MissingBuildFileError as e:
      raise BuildFile.MissingBuildFileError("{message}\n  referenced from {spec}"
                                        .format(message=e.message,
                                                spec=address.spec))

  def parse_build_file_family(self, build_file):
    if build_file not in self._added_build_file_families:
      for bf in build_file.family():
        self.parse_build_file(bf)
    self._added_build_file_families.add(build_file)

  def parse_build_file(self, build_file):
    """Capture TargetProxies from parsing `build_file`.

    Prepare a context for parsing, read a BUILD file from the filesystem, and record the
    TargetProxies generated by executing the code.
    """

    if build_file in self._added_build_files:
      logger.debug('BuildFile {build_file} has already been parsed.'
                   .format(build_file=build_file))
      return

    logger.debug("Parsing BUILD file {build_file}.".format(build_file=build_file))

    try:
      build_file_code = build_file.code()
    except Exception:
      logger.exception("Error parsing {build_file}.".format(build_file=build_file))
      traceback.print_exc()
      raise

    parse_state = self._build_configuration.initialize_parse_state(build_file)
    try:
      Compatibility.exec_function(build_file_code, parse_state.parse_globals)
    except Exception:
      logger.exception("Error parsing {build_file}.".format(build_file=build_file))
      traceback.print_exc()
      raise

    for target_proxy in parse_state.registered_target_proxies:
      logger.debug('Adding {target_proxy} to the proxy build graph with {address}'
                   .format(target_proxy=target_proxy,
                           address=target_proxy.address))

      if target_proxy.address in self._target_proxy_by_address:
        conflicting_target = self._target_proxy_by_address[target_proxy.address]
        if conflicting_target.address.build_file != target_proxy.address.build_file:
          raise BuildFileParser.SiblingConflictException(
              "Both {conflicting_file} and {target_file} define the same target '{target_name}'"
              .format(conflicting_file=conflicting_target.address.build_file,
                      target_file=target_proxy.address.build_file,
                      target_name=conflicting_target.address.target_name))
        raise BuildFileParser.TargetConflictException(
            "File {conflicting_file} defines target '{target_name}' more than once."
            .format(conflicting_file=conflicting_target.address.build_file,
                    target_name=conflicting_target.address.target_name))

      assert target_proxy.address not in self.addresses_by_build_file[build_file], (
          '{address} has already been associated with {build_file} in the build graph.'
          .format(address=target_proxy.address,
                  build_file=build_file))

      self._target_proxy_by_address[target_proxy.address] = target_proxy
      self.addresses_by_build_file[build_file].add(target_proxy.address)
      self._target_proxies_by_build_file[build_file].add(target_proxy)
    self._added_build_files.add(build_file)

    logger.debug("{build_file} produced the following TargetProxies:"
                 .format(build_file=build_file))
    for target_proxy in parse_state.registered_target_proxies:
      logger.debug("  * {target_proxy}".format(target_proxy=target_proxy))

    return parse_state.registered_target_proxies

  def scan(self, root=None):
    """Scans and parses all BUILD files found under ``root``.

    Only BUILD files found under ``root`` are parsed as roots in the graph, but any dependencies of
    targets parsed in the root tree's BUILD files will be followed and this may lead to BUILD files
    outside of ``root`` being parsed and included in the returned build graph.

    :param string root: The path to scan; by default, the build root.
    :returns: A new build graph encapsulating the targets found.
    """
    build_graph = BuildGraph()
    for build_file in BuildFile.scan_buildfiles(root or get_buildroot()):
      self.parse_build_file(build_file)
      for address in self.addresses_by_build_file[build_file]:
        self.inject_address_closure_into_build_graph(address, build_graph)
    return build_graph
