# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.base.address import SyntheticAddress
from pants.base.cmd_line_spec_parser import CmdLineSpecParser

from pants.base.target import Target
from pants_test.base_test import BaseTest


class CmdLineSpecParserTest(BaseTest):
  @property
  def alias_groups(self):
    return {
      'target_aliases': {
        'generic': Target
      }
    }

  def setUp(self):
    super(CmdLineSpecParserTest, self).setUp()

    def add_target(path, name):
      self.add_to_build_file(path, 'generic(name="{name}")\n'.format(name=name))

    add_target('BUILD', 'root')
    add_target('a', 'a')
    add_target('a', 'b')
    add_target('a/b', 'b')
    add_target('a/b', 'c')

    self.spec_parser = CmdLineSpecParser(self.build_root, self.build_file_parser)

  def test_normal(self):
    self.assert_parsed(cmdline_spec=':root', expected=[':root'])
    self.assert_parsed(cmdline_spec='//:root', expected=[':root'])

    self.assert_parsed(cmdline_spec='a', expected=['a'])
    self.assert_parsed(cmdline_spec='a:a', expected=['a'])

    self.assert_parsed(cmdline_spec='a/b', expected=['a/b'])
    self.assert_parsed(cmdline_spec='a/b:b', expected=['a/b'])
    self.assert_parsed(cmdline_spec='a/b:c', expected=['a/b:c'])

  def test_sibling(self):
    self.assert_parsed(cmdline_spec=':', expected=[':root'])
    self.assert_parsed(cmdline_spec='//:', expected=[':root'])

    self.assert_parsed(cmdline_spec='a:', expected=['a', 'a:b'])
    self.assert_parsed(cmdline_spec='//a:', expected=['a', 'a:b'])

    self.assert_parsed(cmdline_spec='a/b:', expected=['a/b', 'a/b:c'])
    self.assert_parsed(cmdline_spec='//a/b:', expected=['a/b', 'a/b:c'])

  def test_sibling_or_descendents(self):
    self.assert_parsed(cmdline_spec='::', expected=[':root', 'a', 'a:b', 'a/b', 'a/b:c'])
    self.assert_parsed(cmdline_spec='//::', expected=[':root', 'a', 'a:b', 'a/b', 'a/b:c'])

    self.assert_parsed(cmdline_spec='a::', expected=['a', 'a:b', 'a/b', 'a/b:c'])
    self.assert_parsed(cmdline_spec='//a::', expected=['a', 'a:b', 'a/b', 'a/b:c'])

    self.assert_parsed(cmdline_spec='a/b::', expected=['a/b', 'a/b:c'])
    self.assert_parsed(cmdline_spec='//a/b::', expected=['a/b', 'a/b:c'])

  def test_cmd_line_affordances(self):
    self.assert_parsed(cmdline_spec='./:root', expected=[':root'])
    self.assert_parsed(cmdline_spec='//./:root', expected=[':root'])
    self.assert_parsed(cmdline_spec='//./a/../:root', expected=[':root'])

    self.assert_parsed(cmdline_spec='a/', expected=['a'])
    self.assert_parsed(cmdline_spec='./a/', expected=['a'])

    self.assert_parsed(cmdline_spec='a/b/:b', expected=['a/b'])
    self.assert_parsed(cmdline_spec='./a/b/:b', expected=['a/b'])

  def test_does_not_exist(self):
    with self.assertRaises(IOError):
      self.spec_parser.parse_addresses('c').next()

    with self.assertRaises(IOError):
      self.spec_parser.parse_addresses('c:').next()

    self.assert_parsed(cmdline_spec='c::', expected=[])

  def assert_parsed(self, cmdline_spec, expected):
    def sort(addresses):
      return sorted(addresses, key=lambda address: address.spec)

    self.assertEqual(sort(SyntheticAddress.parse(addr) for addr in expected),
                     sort(self.spec_parser.parse_addresses(cmdline_spec)))
