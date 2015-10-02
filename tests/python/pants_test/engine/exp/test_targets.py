# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

from pants.base.address import Address
from pants.engine.exp.objects import ValidationError
from pants.engine.exp.targets import Config


class ConfigTest(unittest.TestCase):
  def test_address_no_name(self):
    config = Config(address=Address.parse('a:b'))
    self.assertEqual('b', config.name)

  def test_address_name_conflict(self):
    with self.assertRaises(ValidationError):
      Config(name='a', address=Address.parse('a:b'))

  def test_typename(self):
    self.assertEqual('Config', Config().typename)
    self.assertEqual('aliased', Config(typename='aliased').typename)

    class Subclass(Config):
      pass

    self.assertEqual('Subclass', Subclass().typename)
    self.assertEqual('aliased_subclass', Subclass(typename='aliased_subclass').typename)

  def test_extend_and_merge(self):
    # Resolution should be lazy, so - although its invalid to both extend and merge, we should be
    # able to create the config.
    config = Config(extends=Config(), merges=Config())
    with self.assertRaises(ValidationError):
      # But we should fail when we go to actually inherit.
      config.create()

  def test_extend(self):
    extends = Config(age=32, label='green', items=[],
                     extends=Config(age=42, other=True, items=[1, 2]))

    # Extension is lazy, so we don't pick up the other field yet.
    self.assertNotEqual(Config(age=32, label='green', items=[], other=True), extends)

    # But we do pick it up now.
    self.assertEqual(Config(age=32, label='green', items=[], other=True), extends.create())

  def test_merge(self):
    merges = Config(age=32, items=[3], knobs={'b': False},
                    merges=Config(age=42, other=True, items=[1, 2], knobs={'a': True, 'b': True}))

    # Merging is lazy, so we don't pick up the other field yet.
    self.assertNotEqual(Config(age=32, items=[1, 2, 3], knobs={'a': True, 'b': False}, other=True),
                        merges)

    # But we do pick it up now.
    self.assertEqual(Config(age=32, items=[1, 2, 3], knobs={'a': True, 'b': False}, other=True),
                     merges.create())

  def test_validate_concrete(self):
    class Subclass(Config):
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
