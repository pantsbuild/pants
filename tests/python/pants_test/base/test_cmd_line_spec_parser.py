# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.base.cmd_line_spec_parser import CmdLineSpecParser
from pants.base.specs import DescendantAddresses, SiblingAddresses, SingleAddress
from pants_test.base_test import BaseTest


def single(directory, name=None):
  return SingleAddress(directory, name)


def desc(directory):
  return DescendantAddresses(directory)


def sib(directory):
  return SiblingAddresses(directory)


class CmdLineSpecParserTest(BaseTest):

  def setUp(self):
    super(CmdLineSpecParserTest, self).setUp()
    self._spec_parser = CmdLineSpecParser(self.build_root)

  def test_normal(self):
    self.assert_parsed(':root', single('', 'root'))
    self.assert_parsed('//:root', single('', 'root'))

    self.assert_parsed('a', single('a'))
    self.assert_parsed('a:a', single('a', 'a'))

    self.assert_parsed('a/b', single('a/b'))
    self.assert_parsed('a/b:b', single('a/b', 'b'))
    self.assert_parsed('a/b:c', single('a/b', 'c'))

  def test_sibling(self):
    self.assert_parsed(':', sib(''))
    self.assert_parsed('//:', sib(''))

    self.assert_parsed('a:', sib('a'))
    self.assert_parsed('//a:', sib('a'))

    self.assert_parsed('a/b:', sib('a/b'))
    self.assert_parsed('//a/b:', sib('a/b'))

  def test_sibling_or_descendents(self):
    self.assert_parsed('::', desc(''))
    self.assert_parsed('//::', desc(''))

    self.assert_parsed('a::', desc('a'))
    self.assert_parsed('//a::', desc('a'))

    self.assert_parsed('a/b::', desc('a/b'))
    self.assert_parsed('//a/b::', desc('a/b'))

  def test_absolute(self):
    self.assert_parsed(os.path.join(self.build_root, 'a'), single('a'))
    self.assert_parsed(os.path.join(self.build_root, 'a:a'), single('a', 'a'))
    self.assert_parsed(os.path.join(self.build_root, 'a:'), sib('a'))
    self.assert_parsed(os.path.join(self.build_root, 'a::'), desc('a'))

    with self.assertRaises(CmdLineSpecParser.BadSpecError):
      self.assert_parsed('/not/the/buildroot/a', sib('a'))

  def test_absolute_double_slashed(self):
    # By adding a double slash, we are insisting that this absolute path is actually
    # relative to the buildroot. Thus, it should parse correctly.
    double_absolute = '/' + os.path.join(self.build_root, 'a')
    self.assertEquals('//', double_absolute[:2],
                      'A sanity check we have a leading-// absolute spec')
    self.assert_parsed(double_absolute, single(double_absolute[2:]))

  def test_cmd_line_affordances(self):
    self.assert_parsed('./:root', single('', 'root'))
    self.assert_parsed('//./:root', single('', 'root'))
    self.assert_parsed('//./a/../:root', single('', 'root'))
    self.assert_parsed(os.path.join(self.build_root, './a/../:root'), single('', 'root'))

    self.assert_parsed('a/', single('a'))
    self.assert_parsed('./a/', single('a'))
    self.assert_parsed(os.path.join(self.build_root, './a/'), single('a'))

    self.assert_parsed('a/b/:b', single('a/b', 'b'))
    self.assert_parsed('./a/b/:b', single('a/b', 'b'))
    self.assert_parsed(os.path.join(self.build_root, './a/b/:b'), single('a/b', 'b'))

  def assert_parsed(self, spec_str, expected_spec):
    self.assertEqual(self._spec_parser.parse_spec(spec_str), expected_spec)
