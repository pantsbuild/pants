# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)


import os
import unittest2 as unittest

from pants.backend.android.tasks.aapt_gen import AaptGen


class AaptGenCalculateGenfilesTest(unittest.TestCase):
  """Test the package translation methods in pants.backend.android.aapt_gen."""

  def assert_files(self, package, expected_file):
    self.assertEqual(AaptGen._calculate_genfile(package), expected_file)

  def test_calculate_genfile(self):
    self.assert_files(
      'com.pants.examples.hello',
      os.path.join('bin', 'com', 'pants', 'examples', 'hello', 'R.java'))

    with self.assertRaises(AssertionError):
      self.assert_files(
        'com.pants.examples.hello',
        os.path.join('bin','com', 'pants', 'examples', 'hello'))


  def test_package_path(self):
    self.assertEqual(os.path.join('com', 'pants', 'example', 'tests'),
                     AaptGen.package_path('com.pants.example.tests'))

    with self.assertRaises(AssertionError):
      self.assertEqual(os.path.join('com', 'pants', 'example', 'tests'),
                       AaptGen.package_path('com.pants-example.tests'))

    with self.assertRaises(AssertionError):
      self.assertEqual(os.path.join('com', 'pants', 'example', 'tests'),
                       AaptGen.package_path('com.pants.example'))
