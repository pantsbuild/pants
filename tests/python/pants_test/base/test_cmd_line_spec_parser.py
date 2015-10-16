# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import re

from pants.base.cmd_line_spec_parser import CmdLineSpecParser
from pants.build_graph.address import Address
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.build_graph.target import Target
from pants_test.base_test import BaseTest


class CmdLineSpecParserTest(BaseTest):

  @property
  def alias_groups(self):
    return BuildFileAliases(
      targets={
        'generic': Target
      }
    )

  def setUp(self):
    super(CmdLineSpecParserTest, self).setUp()

    def add_target(path, name):
      self.add_to_build_file(path, 'generic(name="{name}")\n'.format(name=name))

    add_target('BUILD', 'root')
    add_target('a', 'a')
    add_target('a', 'b')
    add_target('a/b', 'b')
    add_target('a/b', 'c')

    self.spec_parser = CmdLineSpecParser(self.build_root, self.address_mapper)

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

  def test_absolute(self):
    self.assert_parsed(cmdline_spec=os.path.join(self.build_root, 'a'), expected=['a'])
    self.assert_parsed(cmdline_spec=os.path.join(self.build_root, 'a:a'), expected=['a'])
    self.assert_parsed(cmdline_spec=os.path.join(self.build_root, 'a:'), expected=['a', 'a:b'])
    self.assert_parsed(cmdline_spec=os.path.join(self.build_root, 'a::'),
                       expected=['a', 'a:b', 'a/b', 'a/b:c'])

    double_absolute = '/' + os.path.join(self.build_root, 'a')
    self.assertEquals('//', double_absolute[:2],
                      'A sanity check we have a leading-// absolute spec')
    with self.assertRaises(self.spec_parser.BadSpecError):
      self.spec_parser.parse_addresses(double_absolute).next()

    with self.assertRaises(self.spec_parser.BadSpecError):
      self.spec_parser.parse_addresses('/not/the/buildroot/a').next()

  def test_cmd_line_affordances(self):
    self.assert_parsed(cmdline_spec='./:root', expected=[':root'])
    self.assert_parsed(cmdline_spec='//./:root', expected=[':root'])
    self.assert_parsed(cmdline_spec='//./a/../:root', expected=[':root'])
    self.assert_parsed(cmdline_spec=os.path.join(self.build_root, './a/../:root'),
                       expected=[':root'])

    self.assert_parsed(cmdline_spec='a/', expected=['a'])
    self.assert_parsed(cmdline_spec='./a/', expected=['a'])
    self.assert_parsed(cmdline_spec=os.path.join(self.build_root, './a/'), expected=['a'])

    self.assert_parsed(cmdline_spec='a/b/:b', expected=['a/b'])
    self.assert_parsed(cmdline_spec='./a/b/:b', expected=['a/b'])
    self.assert_parsed(cmdline_spec=os.path.join(self.build_root, './a/b/:b'), expected=['a/b'])

  def test_cmd_line_spec_list(self):
    self.assert_parsed_list(cmdline_spec_list=['a', 'a/b'], expected=['a', 'a/b'])
    self.assert_parsed_list(cmdline_spec_list=['::'], expected=[':root', 'a', 'a:b', 'a/b', 'a/b:c'])

  def test_does_not_exist(self):
    with self.assertRaises(self.spec_parser.BadSpecError):
      self.spec_parser.parse_addresses('c').next()

    with self.assertRaises(self.spec_parser.BadSpecError):
      self.spec_parser.parse_addresses('c:').next()

    with self.assertRaises(self.spec_parser.BadSpecError):
      self.spec_parser.parse_addresses('c::').next()

  def assert_parsed(self, cmdline_spec, expected):
    def sort(addresses):
      return sorted(addresses, key=lambda address: address.spec)

    self.assertEqual(sort(Address.parse(addr) for addr in expected),
                     sort(self.spec_parser.parse_addresses(cmdline_spec)))

  def assert_parsed_list(self, cmdline_spec_list, expected):
    def sort(addresses):
      return sorted(addresses, key=lambda address: address.spec)

    self.assertEqual(sort(Address.parse(addr) for addr in expected),
                     sort(self.spec_parser.parse_addresses(cmdline_spec_list)))

  def test_spec_excludes(self):
    expected_specs = [':root', 'a', 'a:b', 'a/b', 'a/b:c']

    # This bogus BUILD file gets in the way of parsing.
    self.add_to_build_file('some/dir', 'COMPLETELY BOGUS BUILDFILE)\n')
    with self.assertRaises(CmdLineSpecParser.BadSpecError):
      self.assert_parsed_list(cmdline_spec_list=['::'], expected=expected_specs)

    # Test absolute path in spec_excludes.
    self.spec_parser = CmdLineSpecParser(self.build_root, self.address_mapper,
                                         spec_excludes=[os.path.join(self.build_root, 'some')])
    self.assert_parsed_list(cmdline_spec_list=['::'], expected=expected_specs)

    # Test relative path in spec_excludes.
    self.spec_parser = CmdLineSpecParser(self.build_root, self.address_mapper,
                                         spec_excludes=['some'])
    self.assert_parsed_list(cmdline_spec_list=['::'], expected=expected_specs)

  def test_exclude_target_regexps(self):
    expected_specs = [':root', 'a', 'a:b', 'a/b', 'a/b:c']

    # This bogus BUILD file gets in the way of parsing.
    self.add_to_build_file('some/dir', 'COMPLETELY BOGUS BUILDFILE)\n')
    with self.assertRaises(CmdLineSpecParser.BadSpecError):
      self.assert_parsed_list(cmdline_spec_list=['::'], expected=expected_specs)

    self.spec_parser = CmdLineSpecParser(self.build_root, self.address_mapper,
                                         exclude_target_regexps=[r'.*some/dir.*'])
    self.assert_parsed_list(cmdline_spec_list=['::'], expected=expected_specs)


class CmdLineSpecParserBadBuildTest(BaseTest):

  def setUp(self):
    super(CmdLineSpecParserBadBuildTest, self).setUp()

    self.add_to_build_file('bad/a', 'a_is_bad')
    self.add_to_build_file('bad/b', 'b_is_bad')

    self.spec_parser = CmdLineSpecParser(self.build_root, self.address_mapper)

    self.NO_FAIL_FAST_RE = re.compile(r"""^--------------------
.*
Exception message: name 'a_is_bad' is not defined
 while executing BUILD file FilesystemBuildFile\((/[^/]+)*/bad/a/BUILD\)
 Loading addresses from 'bad/a' failed\.
.*
Exception message: name 'b_is_bad' is not defined
 while executing BUILD file FilesystemBuildFile\((/[^/]+)*T/bad/b/BUILD\)
 Loading addresses from 'bad/b' failed\.
Invalid BUILD files for \[::\]$""", re.DOTALL)

    self.FAIL_FAST_RE = """^name 'a_is_bad' is not defined
 while executing BUILD file FilesystemBuildFile\((/[^/]+)*/bad/a/BUILD\)
 Loading addresses from 'bad/a' failed.$"""

  def test_bad_build_files(self):
    with self.assertRaisesRegexp(self.spec_parser.BadSpecError, self.NO_FAIL_FAST_RE):
      list(self.spec_parser.parse_addresses('::'))

  def test_bad_build_files_fail_fast(self):
    with self.assertRaisesRegexp(self.spec_parser.BadSpecError, self.FAIL_FAST_RE):
      list(self.spec_parser.parse_addresses('::', True))
