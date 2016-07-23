# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

from pants.build_graph.address import Address
from pants.engine.objects import ValidationError
from pants.engine.struct import Struct


class StructTest(unittest.TestCase):

  def test_attribute_error_raised_in_property(self):
    """This tests that Struct#__getattr__ doesn't prevent correct attribution of AttributeErrors."""
    class StructWithProperty(Struct):
      @property
      def some_property(self):
        return self.missing_attribute
    struct2 = StructWithProperty()
    with self.assertRaises(AttributeError) as cm:
      struct2.some_property
    self.assertEqual("'StructWithProperty' object has no attribute 'missing_attribute'",
                     str(cm.exception))

  def test_address_no_name(self):
    config = Struct(address=Address.parse('a:b'))
    self.assertEqual('b', config.name)

  def test_address_name_conflict(self):
    with self.assertRaises(ValidationError):
      Struct(name='a', address=Address.parse('a:b'))

  def test_type_alias(self):
    self.assertEqual('Struct', Struct().type_alias)
    self.assertEqual('aliased', Struct(type_alias='aliased').type_alias)

    class Subclass(Struct):
      pass

    self.assertEqual('Subclass', Subclass().type_alias)
    self.assertEqual('aliased_subclass', Subclass(type_alias='aliased_subclass').type_alias)

  def test_extend(self):
    extends = Struct(age=32, label='green', items=[],
                            extends=Struct(age=42, other=True, items=[1, 2]))

    # Extension is lazy, so we don't pick up the other field yet.
    self.assertNotEqual(Struct(age=32, label='green', items=[], other=True), extends)

    # But we do pick it up now.
    self.assertEqual(Struct(age=32, label='green', items=[], other=True), extends.create())

  def test_merge(self):
    merges = Struct(age=32, items=[3], knobs={'b': False},
                           merges=[Struct(age=42,
                                          other=True,
                                          items=[1, 2],
                                          knobs={'a': True, 'b': True})])

    # Merging is lazy, so we don't pick up the other field yet.
    self.assertNotEqual(Struct(age=32,
                               items=[3, 1, 2],
                               knobs={'a': True, 'b': True},
                               other=True),
                        merges)

    # But we do pick it up now.
    self.assertEqual(Struct(age=32,
                            items=[3, 1, 2],
                            knobs={'a': True, 'b': True},
                            other=True),
                     merges.create())

  def test_extend_and_merge(self):
    extends_and_merges = Struct(age=32, label='green', items=[5],
                                extends=Struct(age=42,
                                               other=True,
                                               knobs={'a': True},
                                               items=[1, 2]),
                                merges=[Struct(age=52,
                                               other=False,
                                               items=[1, 3, 4],
                                               knobs={'a': False, 'b': True}),
                                        Struct(items=[2])])
    self.assertEqual(Struct(age=32,
                            label='green',
                            other=True,
                            items=[5, 1, 3, 4, 2],
                            knobs={'a': False, 'b': True}),
                     extends_and_merges.create())

  def test_validate_concrete(self):
    class Subclass(Struct):
      def validate_concrete(self):
        if self.name != 'jake':
          self.report_validation_error('There is only one true good name.')

    # A valid name.
    jake = Subclass(name='jake')
    jake.validate()

    # An invalid name, but we're abstract, so don't validate yet.
    jack = Subclass(name='jack', abstract=True)
    jack.validate()

    # An invalid name in a concrete instance, this should raise.
    jeb = Subclass(name='jeb')
    with self.assertRaises(ValidationError):
      jeb.validate()
