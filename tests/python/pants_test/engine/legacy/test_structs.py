# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import unittest
from builtins import str

from future.utils import PY3

from pants.engine.legacy.structs import Files


class StructTest(unittest.TestCase):

  def test_filespec_with_excludes(self):
    files = Files(spec_path='')
    self.assertEqual({'globs': []}, files.filespecs)
    files = Files(exclude=['*.md'], spec_path='')
    self.assertEqual({'exclude': [{'globs': ['*.md']}], 'globs': []}, files.filespecs)

  def test_excludes_of_wrong_type(self):
    with self.assertRaises(ValueError) as cm:
      Files(exclude='*.md', spec_path='')
    self.assertEqual('Excludes of type `{}` are not supported: got "*.md"'.format('str' if PY3 else 'unicode'),
                     str(cm.exception))
