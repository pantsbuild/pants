# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import unittest
from builtins import bytes

from pants.util.strutil import camelcase, ensure_binary, ensure_text, pluralize, strip_prefix


# TODO(Eric Ayers): Backfill tests for other methods in strutil.py
class StrutilTest(unittest.TestCase):

  def test_camelcase(self):

    self.assertEqual('Foo', camelcase('foo'))
    self.assertEqual('Foo', camelcase('_foo'))
    self.assertEqual('Foo', camelcase('foo_'))
    self.assertEqual('FooBar', camelcase('foo_bar'))
    self.assertEqual('FooBar', camelcase('foo_bar_'))
    self.assertEqual('FooBar', camelcase('_foo_bar'))
    self.assertEqual('FooBar', camelcase('foo__bar'))
    self.assertEqual('Foo', camelcase('-foo'))
    self.assertEqual('Foo', camelcase('foo-'))
    self.assertEqual('FooBar', camelcase('foo-bar'))
    self.assertEqual('FooBar', camelcase('foo-bar-'))
    self.assertEqual('FooBar', camelcase('-foo-bar'))
    self.assertEqual('FooBar', camelcase('foo--bar'))
    self.assertEqual('FooBar', camelcase('foo-_bar'))

  def test_pluralize(self):
    self.assertEqual('1 bat', pluralize(1, 'bat'))
    self.assertEqual('1 boss', pluralize(1, 'boss'))
    self.assertEqual('2 bats', pluralize(2, 'bat'))
    self.assertEqual('2 bosses', pluralize(2, 'boss'))
    self.assertEqual('0 bats', pluralize(0, 'bat'))
    self.assertEqual('0 bosses', pluralize(0, 'boss'))

  def test_ensure_text(self):
    bytes_val = bytes(bytearray([0xe5, 0xbf, 0xab]))
    self.assertEqual(u'快', ensure_text(bytes_val))
    with self.assertRaises(TypeError):
      ensure_text(45)

  def test_ensure_binary(self):
    unicode_val = u'快'
    self.assertEqual(bytearray([0xe5, 0xbf, 0xab]), ensure_binary(unicode_val))
    with self.assertRaises(TypeError):
      ensure_binary(45)

  def test_strip_prefix(self):
    self.assertEqual('testString', strip_prefix('testString', '//'))
    self.assertEqual('/testString', strip_prefix('/testString', '//'))
    self.assertEqual('testString', strip_prefix('//testString', '//'))
    self.assertEqual('/testString', strip_prefix('///testString', '//'))
    self.assertEqual('//testString', strip_prefix('////testString', '//'))
    self.assertEqual('test//String', strip_prefix('test//String', '//'))
    self.assertEqual('testString//', strip_prefix('testString//', '//'))
