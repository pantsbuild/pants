# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import unittest

from pants.backend.jvm import argfile


class SafeArgTest(unittest.TestCase):
  def test_safe_args_over_max_arg(self):
    # len(args) > max_args, so it should a file should be yielded
    args = ['1', '2', '3', '4']
    with argfile.safe_args(args, options=None, max_args=2, quoter=lambda x: x, delimiter='') as safe_args:
      self.assertEqual(1, len(safe_args))
      arg_file = safe_args[0]
      self.assertTrue(os.path.isfile(arg_file))
      with open(arg_file) as f:
        self.assertEqual(['1234'], f.readlines())

  def test_safe_args_below_max_arg(self):
    # len(args) < max_args, so args should pass through.
    args = ['1', '2', '3', '4']
    with argfile.safe_args(args, options=None, max_args=10, quoter=lambda x: x, delimiter='') as safe_args:
      self.assertTrue(args, safe_args)
