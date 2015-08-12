# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

from pants.base.validation import assert_list


class ParseValidation(unittest.TestCase):

  def test_valid_inputs(self):
    list_result0 = assert_list(["file1.txt"])
    list_result1 = assert_list(["file1.txt", "file2.txt"])
    list_result2 = assert_list(None)
    self.assertEqual(list_result0, ["file1.txt"])  # list of strings gives list of strings
    self.assertEqual(list_result1, ["file1.txt", "file2.txt"])
    self.assertEqual(list_result2, [])  # None is ok by default

  def test_invalid_inputs(self):
    with self.assertRaises(ValueError):
      assert_list({"file2.txt": True})  # Can't pass a dict by default
    with self.assertRaises(ValueError):
      assert_list([["file2.txt"], "file2.txt"])  # All values in list must be stringy values
    with self.assertRaises(ValueError):
      assert_list(None, can_be_none=False)  # The default is ok as None only when can_be_noe is true

  def test_invalid_inputs_with_key_arg(self):
    with self.assertRaisesRegexp(ValueError, "In key 'resources':"):
      assert_list({"file3.txt": "source"}, key_arg='resources')  # Can't pass a dict
    with self.assertRaisesRegexp(ValueError, "In key 'artifacts':"):
      assert_list([["file3.txt"]], key_arg='artifacts')  # All values most be strings
    with self.assertRaisesRegexp(ValueError, "In key 'jars':"):
      assert_list(None, can_be_none=False, key_arg='jars')  # The default is ok as None only when can_be_noe is true
