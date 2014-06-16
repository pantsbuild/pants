# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os

import unittest2 as unittest

from pants.base.build_environment import get_buildroot
from pants.base.build_file_parser import BuildFileParser
from pants.base.dev_backend_loader import load_backends_from_source


class Utf8HeaderTest(unittest.TestCase):

  def test_file_have_coding_utf8(self):
    """
    Look through all .py files and ensure they start with the line '# coding=utf8'
    """
    build_file_parser = BuildFileParser(get_buildroot())
    load_backends_from_source(build_file_parser)

    def has_hand_coded_python_files(tgt):
      return (not tgt.is_synthetic) and tgt.is_original and tgt.has_sources('.py')

    nonconforming_files = []
    for target in build_file_parser.scan().targets(has_hand_coded_python_files):
      for src in target.sources_relative_to_buildroot():
        with open(os.path.join(get_buildroot(), src), 'r') as python_file:
          coding_line = python_file.readline()
          if '' == coding_line and os.path.basename(src) == '__init__.py':
            continue
          if coding_line[0:2] == '#!':
            # Executable file:  look for the coding on the second line.
            coding_line = python_file.readline()
          if not coding_line.rstrip() == '# coding=utf-8':
            nonconforming_files.append(src)

    if len(nonconforming_files) > 0:
      self.fail('Expected these files to contain first line "# coding=utf8": '
                + str(nonconforming_files))
