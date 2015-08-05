# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

from pants.base.generator import TemplateData


class TemplateDataTest(unittest.TestCase):

  def setUp(self):
    self.data = TemplateData(foo='bar', baz=42)

  def test_member_access(self):
    try:
      self.data.bip
      self.fail("Access to undefined template data slots should raise")
    except AttributeError:
      # expected
      pass

  def test_member_mutation(self):
    try:
      self.data.baz = 1 / 137
      self.fail("Mutation of a template data's slots should not be allowed")
    except AttributeError:
      # expected
      pass

  def test_extend(self):
    self.assertEqual(self.data.extend(jake=0.3), TemplateData(baz=42, foo='bar', jake=0.3))

  def test_equals(self):
    self.assertEqual(self.data, TemplateData(baz=42).extend(foo='bar'))
