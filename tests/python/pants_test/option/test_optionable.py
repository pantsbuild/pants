# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

from pants.option.optionable import Optionable


class OptionableTest(unittest.TestCase):
  def test_optionable(self):
    class NoScope(Optionable):
      pass
    with self.assertRaises(NotImplementedError):
      NoScope()

    class NoneScope(Optionable):
      options_scope = None
    with self.assertRaises(NotImplementedError):
      NoneScope()

    class NonStringScope(Optionable):
      options_scope = 42
    with self.assertRaises(NotImplementedError):
      NonStringScope()

    class StringScope(Optionable):
      options_scope = 'good'
    self.assertEquals('good', StringScope.options_scope)

    class Intermediate(Optionable):
      pass

    class Indirect(Intermediate):
      options_scope = 'good'
    self.assertEquals('good', Indirect.options_scope)

  def test_is_valid_scope_name_component(self):
    def check_true(s):
      self.assertTrue(Optionable.is_valid_scope_name_component(s))

    def check_false(s):
      self.assertFalse(Optionable.is_valid_scope_name_component(s))

    check_true('foo')
    check_true('foo-bar0')
    check_true('foo-bar0-1ba22z')

    check_false('Foo')
    check_false('fOo')
    check_false('foo.bar')
    check_false('foo_bar')
    check_false('foo--bar')
    check_false('foo-bar-')
