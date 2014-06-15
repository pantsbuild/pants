# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os

from pants.base.address import BuildFileAddress, parse_spec
from pants.base.build_file import BuildFile


class SpecParser(object):
  """Parses goal target specs; either simple target addresses or else sibling (:) or descendant
  (::) selector forms
  """

  def __init__(self, root_dir, build_file_parser):
    self._root_dir = root_dir
    self._build_file_parser = build_file_parser

  # DEPRECATED!  Specs with BUILD files in them shouldn't be allowed.
  def _get_dir(self, spec):
    path = spec.split(':', 1)[0]
    if os.path.isdir(path):
      return path
    else:
      if os.path.isfile(path):
        return os.path.dirname(path)
      else:
        return spec

  def parse_addresses(self, spec):
    if spec.endswith('::'):
      spec_rel_dir = self._get_dir(spec[:-len('::')])
      spec_dir = os.path.join(self._root_dir, spec_rel_dir)
      for build_file in BuildFile.scan_buildfiles(self._root_dir, spec_dir):
        self._build_file_parser.parse_build_file(build_file)
        for address in self._build_file_parser.addresses_by_build_file[build_file]:
          yield address
    elif spec.endswith(':'):
      spec_rel_dir = self._get_dir(spec[:-len(':')])
      spec_dir = os.path.join(self._root_dir, spec_rel_dir)
      for build_file in BuildFile(self._root_dir, spec_dir).family():
        self._build_file_parser.parse_build_file(build_file)
        for address in self._build_file_parser.addresses_by_build_file[build_file]:
          yield address
    else:
      spec_path, target_name = parse_spec(spec)
      build_file = BuildFile(self._root_dir, spec_path)
      yield BuildFileAddress(build_file, target_name)

