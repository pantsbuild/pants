# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os

from twitter.common.collections import OrderedSet

from pants.base.address import BuildFileAddress, parse_spec
from pants.base.build_file import BuildFile


class CmdLineSpecParser(object):
  """Parses target address specs as passed from the command line.

  Supports simple target addresses as well as sibling (:) and descendant (::) selector forms.
  Also supports some flexibility in the path portion of the spec to allow for more natural command
  line use cases like tab completion leaving a trailing / for directories and relative paths, ie::

    ./src/::

  Is a valid command line spec even though its not a valid BUILD file spec.  Its normalized to::

    src::

  If you have a list of specs to consume, you can also indicate that some targets should be
  subtracted from the set as follows::

     src::  ^src/broken:test

  The above expression would choose every target under src except for src/broken:test
  """

  def __init__(self, root_dir, build_file_parser):
    self._root_dir = root_dir
    self._build_file_parser = build_file_parser

  def parse_addresses(self, specs):
    """Process a list of command line specs and perform expansion.  This method can expand a list
    of command line specs, some of which may be subtracted from the  return value if they include
    the prefix '^'
    :param spec_list: either a single spec string or a list of spec strings.
    :return: a generator of specs parsed into addresses.
    """

    if isinstance(specs, basestring):
      specs = [ specs ]

    addresses = OrderedSet()
    addresses_to_remove = set()

    for spec in specs:
      if spec.startswith('^'):
        for address in self._parse_spec(spec.lstrip('^')):
          addresses_to_remove.add(address)
      else:
        for address in self._parse_spec(spec):
          addresses.add(address)
    for result in addresses - addresses_to_remove:
      yield result

  def _parse_spec(self, spec):
    def normalize_spec_path(path):
      path = os.path.join(self._root_dir, path.lstrip('//'))
      normalized = os.path.relpath(os.path.realpath(path), self._root_dir)
      if normalized == '.':
        normalized = ''
      return normalized

    if spec.endswith('::'):
      spec_path = spec[:-len('::')]
      spec_dir = normalize_spec_path(spec_path)
      for build_file in BuildFile.scan_buildfiles(self._root_dir, spec_dir):
        self._build_file_parser.parse_build_file(build_file)
        for address in self._build_file_parser.addresses_by_build_file[build_file]:
          yield address
    elif spec.endswith(':'):
      spec_path = spec[:-len(':')]
      spec_dir = normalize_spec_path(spec_path)
      for build_file in BuildFile(self._root_dir, spec_dir).family():
        self._build_file_parser.parse_build_file(build_file)
        for address in self._build_file_parser.addresses_by_build_file[build_file]:
          yield address
    else:
      spec_parts = spec.rsplit(':', 1)
      spec_parts[0] = normalize_spec_path(spec_parts[0])
      spec_path, target_name = parse_spec(':'.join(spec_parts))

      build_file = BuildFile(self._root_dir, spec_path)
      yield BuildFileAddress(build_file, target_name)

