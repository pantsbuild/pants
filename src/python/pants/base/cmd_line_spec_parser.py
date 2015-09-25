# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
import re
import traceback
from collections import defaultdict

import six
from twitter.common.collections import OrderedSet, maybe_list

from pants.base.address import Address, parse_spec
from pants.base.address_lookup_error import AddressLookupError
from pants.base.build_file import BuildFile


logger = logging.getLogger(__name__)


# Note: In general, 'spec' should not be a user visible term, it is usually appropriate to
# substitute 'address' for a spec resolved to an address, or 'address selector' if you are
# referring to an unresolved spec string.
class CmdLineSpecParser(object):
  """Parses address selectors as passed from the command line.

  Supports simple target addresses as well as sibling (:) and descendant (::) selector forms.
  Also supports some flexibility in the path portion of the spec to allow for more natural command
  line use cases like tab completion leaving a trailing / for directories and relative paths, ie both
  of these::

    ./src/::
    /absolute/path/to/project/src/::

  Are valid command line specs even though they are not a valid BUILD file specs.  They're both
  normalized to::

    src::

  The above expression would choose every target under src except for src/broken:test
  """

  # Target specs are mapped to the patterns which match them, if any. This variable is a key for
  # specs which don't match any exclusion regexps. We know it won't already be in the list of
  # patterns, because the asterisks in its name make it an invalid regexp.
  _UNMATCHED_KEY = '** unmatched **'

  class BadSpecError(Exception):
    """Indicates an invalid command line address selector."""

  def __init__(self, root_dir, address_mapper, spec_excludes=None, exclude_target_regexps=None):
    self._root_dir = os.path.realpath(root_dir)
    self._address_mapper = address_mapper
    self._spec_excludes = spec_excludes
    self._exclude_target_regexps = exclude_target_regexps or []
    self._exclude_patterns = [re.compile(pattern) for pattern in self._exclude_target_regexps]
    self._excluded_target_map = defaultdict(set)  # pattern -> targets (for debugging)

  def _not_excluded_address(self, address):
    return self._not_excluded_spec(address.spec)

  def _not_excluded_spec(self, spec):
    for pattern in self._exclude_patterns:
      if pattern.search(spec) is not None:
        self._excluded_target_map[pattern.pattern].add(spec)
        return False
    self._excluded_target_map[CmdLineSpecParser._UNMATCHED_KEY].add(spec)
    return True

  def parse_addresses(self, specs, fail_fast=False):
    """Process a list of command line specs and perform expansion.  This method can expand a list
    of command line specs.
    :param list specs: either a single spec string or a list of spec strings.
    :return: a generator of specs parsed into addresses.
    :raises: CmdLineSpecParser.BadSpecError if any of the address selectors could not be parsed.
    """
    specs = maybe_list(specs)

    addresses = OrderedSet()
    for spec in specs:
      for address in self._parse_spec(spec, fail_fast):
        addresses.add(address)

    results = filter(self._not_excluded_address, addresses)

    # Print debug information about the excluded targets
    if logger.getEffectiveLevel() <= logging.DEBUG and self._exclude_patterns:
      logger.debug('excludes:\n  {excludes}'
                   .format(excludes='\n  '.join(self._exclude_target_regexps)))
      targets = ', '.join(self._excluded_target_map[CmdLineSpecParser._UNMATCHED_KEY])
      logger.debug('Targets after excludes: {targets}'.format(targets=targets))
      excluded_count = 0
      for pattern, targets in six.iteritems(self._excluded_target_map):
        if pattern != CmdLineSpecParser._UNMATCHED_KEY:
          logger.debug('Targets excluded by pattern {pattern}\n  {targets}'
                       .format(pattern=pattern,
                               targets='\n  '.join(targets)))
          excluded_count += len(targets)
      logger.debug('Excluded {count} target{plural}.'
                   .format(count=excluded_count,
                           plural=('s' if excluded_count != 1 else '')))
    return results

  def _parse_spec(self, spec, fail_fast=False):
    def normalize_spec_path(path):
      is_abs = not path.startswith('//') and os.path.isabs(path)
      if is_abs:
        path = os.path.realpath(path)
        if os.path.commonprefix([self._root_dir, path]) != self._root_dir:
          raise self.BadSpecError('Absolute address path {0} does not share build root {1}'
                                  .format(path, self._root_dir))
      else:
        if path.startswith('//'):
          path = path[2:]
        path = os.path.join(self._root_dir, path)

      normalized = os.path.relpath(path, self._root_dir)
      if normalized == '.':
        normalized = ''
      return normalized

    errored_out = []

    if spec.endswith('::'):
      addresses = set()
      spec_path = spec[:-len('::')]
      spec_dir = normalize_spec_path(spec_path)
      try:
        build_files = self._address_mapper.scan_buildfiles(self._root_dir, spec_dir,
                                                           spec_excludes=self._spec_excludes)
      except (BuildFile.BuildFileError, AddressLookupError) as e:
        raise self.BadSpecError(e)

      for build_file in build_files:
        try:
          # This attempts to filter out broken BUILD files before we parse them.
          if self._not_excluded_spec(build_file.spec_path):
            addresses.update(self._address_mapper.addresses_in_spec_path(build_file.spec_path))
        except (BuildFile.BuildFileError, AddressLookupError) as e:
          if fail_fast:
            raise self.BadSpecError(e)
          errored_out.append('--------------------')
          errored_out.append(traceback.format_exc())
          errored_out.append('Exception message: {0}'.format(e))

      if errored_out:
        error_msg = '\n'.join(errored_out + ["Invalid BUILD files for [{0}]".format(spec)])
        raise self.BadSpecError(error_msg)
      return addresses

    elif spec.endswith(':'):
      spec_path = spec[:-len(':')]
      spec_dir = normalize_spec_path(spec_path)
      try:
        return set(self._address_mapper.addresses_in_spec_path(spec_dir))
      except AddressLookupError as e:
        raise self.BadSpecError(e)
    else:
      spec_parts = spec.rsplit(':', 1)
      spec_parts[0] = normalize_spec_path(spec_parts[0])
      spec_path, target_name = parse_spec(':'.join(spec_parts))
      try:
        self._address_mapper.from_cache(self._root_dir, spec_path)
      except BuildFile.BuildFileError as e:
        raise self.BadSpecError(e)
      return {Address(spec_path, target_name)}
