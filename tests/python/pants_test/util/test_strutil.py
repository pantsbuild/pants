# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

from pants.util.strutil import camelcase, ensure_binary, ensure_text, pluralize


# TODO(Eric Ayers): Backfill tests for other methods in strutil.py
class StrutilTest(unittest.TestCase):

  def test_camelcase(self):

    self.assertEquals('Foo', camelcase('foo'))
    self.assertEquals('Foo', camelcase('_foo'))
    self.assertEquals('Foo', camelcase('foo_'))
    self.assertEquals('FooBar', camelcase('foo_bar'))
    self.assertEquals('FooBar', camelcase('foo_bar_'))
    self.assertEquals('FooBar', camelcase('_foo_bar'))
    self.assertEquals('FooBar', camelcase('foo__bar'))
    self.assertEquals('Foo', camelcase('-foo'))
    self.assertEquals('Foo', camelcase('foo-'))
    self.assertEquals('FooBar', camelcase('foo-bar'))
    self.assertEquals('FooBar', camelcase('foo-bar-'))
    self.assertEquals('FooBar', camelcase('-foo-bar'))
    self.assertEquals('FooBar', camelcase('foo--bar'))
    self.assertEquals('FooBar', camelcase('foo-_bar'))

  def test_pluralize(self):
    self.assertEquals('1 bat', pluralize(1, 'bat'))
    self.assertEquals('1 boss', pluralize(1, 'boss'))
    self.assertEquals('2 bats', pluralize(2, 'bat'))
    self.assertEquals('2 bosses', pluralize(2, 'boss'))
    self.assertEquals('0 bats', pluralize(0, 'bat'))
    self.assertEquals('0 bosses', pluralize(0, 'boss'))

  def test_ensure_text(self):
    bytes_val = bytes(bytearray([0xe5, 0xbf, 0xab]))
    self.assertEquals(u'快', ensure_text(bytes_val))
    with self.assertRaises(TypeError):
      ensure_text(45)

  def test_ensure_bytes(self):
    unicode_val = u'快'
    self.assertEquals(bytearray([0xe5, 0xbf, 0xab]), ensure_binary(unicode_val))
    with self.assertRaises(TypeError):
      ensure_binary(45)
