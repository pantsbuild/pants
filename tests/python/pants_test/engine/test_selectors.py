# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

from pants.engine.selectors import Select, SelectDependencies, SelectProjection, SelectVariant


class AClass(object):
  pass


class SelectorsTest(unittest.TestCase):
  def test_select_repr(self):
    self.assert_repr("Select(AClass)", Select(AClass))
    self.assert_repr("Select(AClass, optional=True)", Select(AClass, optional=True))

  def test_variant_repr(self):
    self.assert_repr("SelectVariant(AClass, u'field')", SelectVariant(AClass, 'field'))

  def test_dependencies_repr(self):
    self.assert_repr("SelectDependencies(AClass, AClass)", SelectDependencies(AClass, AClass))
    self.assert_repr("SelectDependencies(AClass, AClass, u'some_field')",
                     SelectDependencies(AClass, AClass, field='some_field'))
    self.assert_repr("SelectDependencies(AClass, AClass, u'some_field', field_types=(AClass,))",
                     SelectDependencies(AClass, AClass, field='some_field', field_types=(AClass,)))
    self.assert_repr("SelectDependencies(AClass, AClass)",
                     SelectDependencies(AClass, AClass))

  def test_projection_repr(self):
    self.assert_repr("SelectProjection(AClass, AClass, u'field', AClass)",
                     SelectProjection(AClass, AClass, 'field', AClass))

  def assert_repr(self, expected, selector):
    self.assertEqual(expected, repr(selector))

  def test_select_variant_requires_string_key(self):
    with self.assertRaises(ValueError):
      SelectVariant(AClass, None)
