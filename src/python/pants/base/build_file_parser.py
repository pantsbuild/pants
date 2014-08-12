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
from pants.base.build_environment import get_buildroot, pants_version
from pants.base.build_file import BuildFile
from pants.base.build_graph import BuildGraph


logger = logging.getLogger(__name__)


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

  def registered_aliases(self):
    """Returns a copy of the registered build file aliases this build file parser uses."""
    return self._build_configuration.registered_aliases()

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

  def address_map_from_spec_path(self, spec_path):
    build_file = BuildFile.from_cache(self._root_dir, spec_path)
    family_address_map_by_build_file = self.parse_build_file_family(build_file)
    address_map = {}
    for build_file, sibling_address_map in family_address_map_by_build_file.items():
      address_map.update(sibling_address_map)
    return address_map

  def parse_build_file_family(self, build_file):
    family_address_map_by_build_file = {}  # {build_file: {address: addressable}}
    for bf in build_file.family():
      bf_address_map = self.parse_build_file(bf)
      for address, addressable in bf_address_map.items():
        for sibling_build_file, sibling_address_map in family_address_map_by_build_file.items():
          if address in sibling_address_map:
            raise BuildFileParser.SiblingConflictException(
              "Both {conflicting_file} and {addressable_file} define the same address: "
              "'{target_name}'"
              .format(conflicting_file=sibling_build_file,
                      addressable_file=address.build_file,
                      target_name=address.target_name))
      family_address_map_by_build_file[bf] = bf_address_map
    return family_address_map_by_build_file

  def parse_build_file(self, build_file):
    """Capture Addressable instances from parsing `build_file`.
    Prepare a context for parsing, read a BUILD file from the filesystem, and return the
    Addressable instances generated by executing the code.
    """

    logger.debug("Parsing BUILD file {build_file}."
                 .format(build_file=build_file))

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

    address_map = {}
    for address, addressable in parse_state.registered_addressable_instances:
      logger.debug('Adding {addressable} to the BuildFileParser address map with {address}'
                   .format(addressable=addressable,
                           address=address))
      if address in address_map:
        conflicting_addressable = address_map[address]
        raise BuildFileParser.TargetConflictException(
          "File {conflicting_file} defines address '{target_name}' more than once."
          .format(conflicting_file=address.build_file,
                  target_name=address.target_name))
      address_map[address] = addressable

    logger.debug("{build_file} produced the following Addressables:"
                 .format(build_file=build_file))
    for address, addressable in address_map.items():
      logger.debug("  * {address}: {addressable}"
                   .format(address=address,
                           addressable=addressable))
    return address_map
