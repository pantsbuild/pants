# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from collections import defaultdict
import os
import re

from twitter.common.collections import maybe_list, OrderedSet

from pants.base.address import BuildFileAddress, parse_spec
from pants.base.build_file import BuildFile


class CmdLineSpecParser(object):
  """Parses target address specs as passed from the command line.

  Supports simple target addresses as well as sibling (:) and descendant (::) selector forms.
  Also supports some flexibility in the path portion of the spec to allow for more natural command
  line use cases like tab completion leaving a trailing / for directories and relative paths, ie both
  of these::

    ./src/::
    /absolute/path/to/project/src/::

  Are valid command line specs even though they are not a valid BUILD file specs.  They're both
  normalized to::

    src::

  If you have a list of specs to consume, you can also indicate that some targets should be
  subtracted from the set as follows::

     src::  ^src/broken:test

  The above expression would choose every target under src except for src/broken:test
  """

  # Target specs are mapped to the patterns which match them, if any. This variable is a key for
  # specs which don't match any exclusion regexes. We know it won't already be in the list of
  # patterns, because the asterisks in its name make it an invalid regex.
  _UNMATCHED_KEY = '** unmatched **'

  # TODO(John Sirois): Establish BuildFile And BuildFileAddressMapper exception discipline.  These
  # types should not be raising IOError.

  class BadSpecError(Exception):
    """Indicates an invalid command line address spec."""

  def __init__(self, root_dir, address_mapper, target_excludes_opts=[]):
    def _setup_exclude_patterns():
      patterns = []
      for pattern in target_excludes_opts:
        patterns.append(re.compile(pattern))
      return patterns

    self._root_dir = os.path.realpath(root_dir)
    self._address_mapper = address_mapper
    self._target_excludes_opts = target_excludes_opts
    self._exclude_patterns = _setup_exclude_patterns()
    self._excluded_target_map = defaultdict(set)  # pattern -> targets (for debugging)

  def _not_excluded(self, address):
    spec = address.spec
    for pattern in self._exclude_patterns:
      if pattern.search(spec) is not None:
        self._excluded_target_map[pattern.pattern].add(spec)
        return False
    self._excluded_target_map[CmdLineSpecParser._UNMATCHED_KEY].add(spec)
    return True

  def parse_addresses(self, specs):
    """Process a list of command line specs and perform expansion.  This method can expand a list
    of command line specs, some of which may be subtracted from the  return value if they include
    the prefix '^'
    :param list specs: either a single spec string or a list of spec strings.
    :return: a generator of specs parsed into addresses.
    :raises: CmdLineSpecParser.BadSpecError if any of the specs could not be parsed.
    """
    specs = maybe_list(specs)

    addresses = OrderedSet()
    addresses_to_remove = set()

    for spec in specs:
      if spec.startswith('^'):
        for address in self._parse_spec(spec.lstrip('^')):
          addresses_to_remove.add(address)
      else:
        for address in self._parse_spec(spec):
          addresses.add(address)

    return filter(self._not_excluded,  addresses - addresses_to_remove)

  def log_excludes_info(self, logger):
    """ Print debug info for excluded specs"""
    if self._exclude_patterns:
      logger.debug('excludes:\n  {excludes}'
                   .format(excludes='\n  '.join(self._target_excludes_opts)))
      targets = ', '.join(self._excluded_target_map[CmdLineSpecParser._UNMATCHED_KEY])
      logger.debug('Targets after excludes: {targets}'.format(targets=targets))
      for pattern, targets in self._excluded_target_map.iteritems():
        excluded_count = 0
        if pattern != CmdLineSpecParser._UNMATCHED_KEY:
          logger.debug('Targets excluded by pattern {pattern}\n  {targets}'
                       .format(pattern=pattern,
                               targets='\n  '.join(targets)))
          excluded_count += len(targets)
      logger.debug('Excluded {count} target{plural}.'
                   .format(count=excluded_count,
                           plural=('s' if excluded_count != 1 else '')))

  def _parse_spec(self, spec):
    def normalize_spec_path(path):
      is_abs = not path.startswith('//') and os.path.isabs(path)
      if is_abs:
        path = os.path.realpath(path)
        if os.path.commonprefix([self._root_dir, path]) != self._root_dir:
          raise self.BadSpecError('Absolute spec path {0} does not share build root {1}'
                                  .format(path, self._root_dir))
      else:
        if path.startswith('//'):
          path = path[2:]
        path = os.path.join(self._root_dir, path)

      normalized = os.path.relpath(path, self._root_dir)
      if normalized == '.':
        normalized = ''
      return normalized

    if spec.endswith('::'):
      addresses = set()
      spec_path = spec[:-len('::')]
      spec_dir = normalize_spec_path(spec_path)
      if not os.path.isdir(os.path.join(self._root_dir, spec_dir)):
        raise self.BadSpecError('Can only recursive glob directories and {0} is not a valid dir'
                                .format(spec_dir))
      try:
        for build_file in BuildFile.scan_buildfiles(self._root_dir, spec_dir):
          addresses.update(self._address_mapper.addresses_in_spec_path(build_file.spec_path))
        return addresses
      except (IOError, BuildFile.MissingBuildFileError) as e:
        raise self.BadSpecError(e)
    elif spec.endswith(':'):
      spec_path = spec[:-len(':')]
      spec_dir = normalize_spec_path(spec_path)
      try:
        return set(self._address_mapper.addresses_in_spec_path(spec_dir))
      except (IOError, BuildFile.MissingBuildFileError) as e:
        raise self.BadSpecError(e)
    else:
      spec_parts = spec.rsplit(':', 1)
      spec_parts[0] = normalize_spec_path(spec_parts[0])
      spec_path, target_name = parse_spec(':'.join(spec_parts))
      try:
        build_file = BuildFile.from_cache(self._root_dir, spec_path)
        return set([BuildFileAddress(build_file, target_name)])
      except (IOError, BuildFile.MissingBuildFileError) as e:
        raise self.BadSpecError(e)
