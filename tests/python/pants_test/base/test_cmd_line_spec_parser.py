# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.base.cmd_line_spec_parser import CmdLineSpecParser
from pants_test.base_test import BaseTest


class CmdLineSpecParserTest(BaseTest):

  def setUp(self):
    super(CmdLineSpecParserTest, self).setUp()
    self._spec_parser = CmdLineSpecParser(self.build_root)

  def test_normal(self):
    self.assert_parsed(':root', expected=[':root'])
    self.assert_parsed('//:root', expected=[':root'])

    self.assert_parsed('a', expected=['a'])
    self.assert_parsed('a:a', expected=['a'])

    self.assert_parsed('a/b', expected=['a/b'])
    self.assert_parsed('a/b:b', expected=['a/b'])
    self.assert_parsed('a/b:c', expected=['a/b:c'])

  def test_sibling(self):
    self.assert_parsed(':', expected=[':root'])
    self.assert_parsed('//:', expected=[':root'])

    self.assert_parsed('a:', expected=['a', 'a:b'])
    self.assert_parsed('//a:', expected=['a', 'a:b'])

    self.assert_parsed('a/b:', expected=['a/b', 'a/b:c'])
    self.assert_parsed('//a/b:', expected=['a/b', 'a/b:c'])

  def test_sibling_or_descendents(self):
    self.assert_parsed('::', expected=[':root', 'a', 'a:b', 'a/b', 'a/b:c'])
    self.assert_parsed('//::', expected=[':root', 'a', 'a:b', 'a/b', 'a/b:c'])

    self.assert_parsed('a::', expected=['a', 'a:b', 'a/b', 'a/b:c'])
    self.assert_parsed('//a::', expected=['a', 'a:b', 'a/b', 'a/b:c'])

    self.assert_parsed('a/b::', expected=['a/b', 'a/b:c'])
    self.assert_parsed('//a/b::', expected=['a/b', 'a/b:c'])

  def test_absolute(self):
    self.assert_parsed(os.path.join(self.build_root, 'a'), expected=['a'])
    self.assert_parsed(os.path.join(self.build_root, 'a:a'), expected=['a'])
    self.assert_parsed(os.path.join(self.build_root, 'a:'), expected=['a', 'a:b'])
    self.assert_parsed(os.path.join(self.build_root, 'a::'),
                        expected=['a', 'a:b', 'a/b', 'a/b:c'])

    double_absolute = '/' + os.path.join(self.build_root, 'a')
    self.assertEquals('//', double_absolute[:2],
                      'A sanity check we have a leading-// absolute spec')
    with self.assertRaises(self.spec_parser.BadSpecError):
      self.spec_parser.parse_addresses(double_absolute).next()

    with self.assertRaises(self.spec_parser.BadSpecError):
      self.spec_parser.parse_addresses('/not/the/buildroot/a').next()

  def test_cmd_line_affordances(self):
    self.assert_parsed('./:root', expected=[':root'])
    self.assert_parsed('//./:root', expected=[':root'])
    self.assert_parsed('//./a/../:root', expected=[':root'])
    self.assert_parsed(os.path.join(self.build_root, './a/../:root'),
                       expected=[':root'])

    self.assert_parsed('a/', expected=['a'])
    self.assert_parsed('./a/', expected=['a'])
    self.assert_parsed(os.path.join(self.build_root, './a/'), expected=['a'])

    self.assert_parsed('a/b/:b', expected=['a/b'])
    self.assert_parsed('./a/b/:b', expected=['a/b'])
    self.assert_parsed(os.path.join(self.build_root, './a/b/:b'), expected=['a/b'])

  def test_cmd_line_spec_list(self):
    self.assert_parsed('a', 'a/b', expected=['a', 'a/b'])
    self.assert_parsed('::', expected=[':root', 'a', 'a:b', 'a/b', 'a/b:c'])

  def assert_parsed(self, spec_str, expected_spec):
    self.assertEqual(self._spec_parser.parse_spec(spec_str), expected_spec)
