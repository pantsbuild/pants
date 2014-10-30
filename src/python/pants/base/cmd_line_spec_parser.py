# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
import traceback

from twitter.common.collections import maybe_list, OrderedSet

from pants.base.address import BuildFileAddress, parse_spec
from pants.base.address_lookup_error import AddressLookupError
from pants.base.build_file import BuildFile


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

  If you have a list of specs to consume, you can also indicate that some targets should be
  subtracted from the set as follows::

     src::  ^src/broken:test

  The above expression would choose every target under src except for src/broken:test
  """


  class BadSpecError(Exception):
    """Indicates an invalid command line address selector."""

  def __init__(self, root_dir, address_mapper, spec_excludes=None):
    self._root_dir = os.path.realpath(root_dir)
    self._address_mapper = address_mapper
    self._spec_excludes = spec_excludes

  def parse_addresses(self, specs, fail_fast=False):
    """Process a list of command line specs and perform expansion.  This method can expand a list
    of command line specs, some of which may be subtracted from the  return value if they include
    the prefix '^'
    :param list specs: either a single spec string or a list of spec strings.
    :return: a generator of specs parsed into addresses.
    :raises: CmdLineSpecParser.BadSpecError if any of the address selectors could not be parsed.
    """
    specs = maybe_list(specs)

    addresses = OrderedSet()
    addresses_to_remove = set()
    for spec in specs:
      if spec.startswith('^'):
        for address in self._parse_spec(spec.lstrip('^'), fail_fast):
          addresses_to_remove.add(address)
      else:
        for address in self._parse_spec(spec, fail_fast):
          addresses.add(address)
    for result in addresses - addresses_to_remove:
      yield result

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
      if not os.path.isdir(os.path.join(self._root_dir, spec_dir)):
        raise self.BadSpecError('Can only recursive glob directories and {0} is not a valid dir'
                                .format(spec_dir))
      try:
        build_files = BuildFile.scan_buildfiles(self._root_dir, spec_dir, spec_excludes=self._spec_excludes)
      except (BuildFile.BuildFileError, AddressLookupError) as e:
        raise self.BadSpecError(e)

      for build_file in build_files:
        try:
          addresses.update(self._address_mapper.addresses_in_spec_path(build_file.spec_path))
        except (BuildFile.BuildFileError, AddressLookupError) as e:
          if fail_fast:
            raise self.BadSpecError(e)
          errored_out.append('--------------------')
          errored_out.append(traceback.format_exc())
          errored_out.append('Exception message: {0}'.format(e.message))

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
        build_file = BuildFile.from_cache(self._root_dir, spec_path)
        return set([BuildFileAddress(build_file, target_name)])
      except BuildFile.BuildFileError as e:
        raise self.BadSpecError(e)
