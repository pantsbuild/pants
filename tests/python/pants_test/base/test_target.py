# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import unittest

from pants.base.target import Target


class TargetTest(unittest.TestCase):

  def test_get_build_file_alias_is_not_overriden(self):
    class FakeInvalidTarget(Target): pass
    self.assertRaises(NotImplementedError, FakeInvalidTarget.get_build_file_alias)

  def test_get_build_file_alias_is_overriden(self):
    fake_valid_target_alias = 'fake_valid_target'
    class FakeValidTarget(Target):
      @classmethod
      def get_build_file_alias(cls):
        return fake_valid_target_alias
    self.assertEquals(fake_valid_target_alias, FakeValidTarget.get_build_file_alias())
