# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import unittest
from contextlib import contextmanager

from pants.base.build_file import BuildFile
from pants.base.build_root import BuildRoot
from pants.base.file_system_project_tree import FileSystemProjectTree
from pants.build_graph.address import (Address, BuildFileAddress, InvalidSpecPath,
                                       InvalidTargetName, parse_spec)
from pants.util.contextutil import pushd, temporary_dir
from pants.util.dirutil import touch


class ParseSpecTest(unittest.TestCase):
  def test_parse_spec(self):
    spec_path, target_name = parse_spec('a/b/c')
    self.assertEqual(spec_path, 'a/b/c')
    self.assertEqual(target_name, 'c')

    spec_path, target_name = parse_spec('a/b/c:c')
    self.assertEqual(spec_path, 'a/b/c')
    self.assertEqual(target_name, 'c')

    spec_path, target_name = parse_spec('a/b/c', relative_to='here')  # no effect - we have a path
    self.assertEqual(spec_path, 'a/b/c')
    self.assertEqual(target_name, 'c')

  def test_parse_local_spec(self):
    spec_path, target_name = parse_spec(':c')
    self.assertEqual(spec_path, '')
    self.assertEqual(target_name, 'c')

    spec_path, target_name = parse_spec(':c', relative_to='here')
    self.assertEqual(spec_path, 'here')
    self.assertEqual(target_name, 'c')

  def test_parse_absolute_spec(self):
    spec_path, target_name = parse_spec('//a/b/c')
    self.assertEqual(spec_path, 'a/b/c')
    self.assertEqual(target_name, 'c')

    spec_path, target_name = parse_spec('//a/b/c:c')
    self.assertEqual(spec_path, 'a/b/c')
    self.assertEqual(target_name, 'c')

    spec_path, target_name = parse_spec('//:c')
    self.assertEqual(spec_path, '')
    self.assertEqual(target_name, 'c')

  def test_parse_bad_spec_non_normalized(self):
    self.do_test_bad_spec_path('..')
    self.do_test_bad_spec_path('.')

    self.do_test_bad_spec_path('//..')
    self.do_test_bad_spec_path('//.')

    self.do_test_bad_spec_path('a/.')
    self.do_test_bad_spec_path('a/..')
    self.do_test_bad_spec_path('../a')
    self.do_test_bad_spec_path('a/../a')

    self.do_test_bad_spec_path('a/')
    self.do_test_bad_spec_path('a/b/')

  def test_parse_bad_spec_bad_path(self):
    self.do_test_bad_spec_path('/a')
    self.do_test_bad_spec_path('///a')

  def test_parse_bad_spec_bad_name(self):
    self.do_test_bad_target_name('a:')
    self.do_test_bad_target_name('a::')
    self.do_test_bad_target_name('//')

  def test_parse_bad_spec_build_trailing_path_component(self):
    self.do_test_bad_spec_path('BUILD')
    self.do_test_bad_spec_path('BUILD.suffix')
    self.do_test_bad_spec_path('//BUILD')
    self.do_test_bad_spec_path('//BUILD.suffix')
    self.do_test_bad_spec_path('a/BUILD')
    self.do_test_bad_spec_path('a/BUILD.suffix')
    self.do_test_bad_spec_path('//a/BUILD')
    self.do_test_bad_spec_path('//a/BUILD.suffix')
    self.do_test_bad_spec_path('a/BUILD:b')
    self.do_test_bad_spec_path('a/BUILD.suffix:b')
    self.do_test_bad_spec_path('//a/BUILD:b')
    self.do_test_bad_spec_path('//a/BUILD.suffix:b')

  def test_banned_chars_in_target_name(self):
    # move to do_test_bad_spec_path after deprecation
    self.assertEquals('c@d', Address(*parse_spec('a/b:c@d')).target_name)

  def do_test_bad_spec_path(self, spec):
    with self.assertRaises(InvalidSpecPath):
      Address(*parse_spec(spec))

  def do_test_bad_target_name(self, spec):
    with self.assertRaises(InvalidTargetName):
      Address(*parse_spec(spec))


class BaseAddressTest(unittest.TestCase):
  @contextmanager
  def workspace(self, *buildfiles):
    with temporary_dir() as root_dir:
      with BuildRoot().temporary(root_dir):
        with pushd(root_dir):
          for buildfile in buildfiles:
            touch(os.path.join(root_dir, buildfile))
          yield os.path.realpath(root_dir)

  def assert_address(self, spec_path, target_name, address):
    self.assertEqual(spec_path, address.spec_path)
    self.assertEqual(target_name, address.target_name)


class AddressTest(BaseAddressTest):
  def test_equivalence(self):
    self.assertNotEqual("Not really an address", Address('a/b', 'c'))

    self.assertEqual(Address('a/b', 'c'), Address('a/b', 'c'))
    self.assertEqual(Address('a/b', 'c'), Address.parse('a/b:c'))
    self.assertEqual(Address.parse('a/b:c'), Address.parse('a/b:c'))

  def test_parse(self):
    self.assert_address('a/b', 'target', Address.parse('a/b:target'))
    self.assert_address('a/b', 'target', Address.parse('//a/b:target'))
    self.assert_address('a/b', 'b', Address.parse('a/b'))
    self.assert_address('a/b', 'b', Address.parse('//a/b'))
    self.assert_address('a/b', 'target', Address.parse(':target', relative_to='a/b'))
    self.assert_address('', 'target', Address.parse('//:target', relative_to='a/b'))
    self.assert_address('', 'target', Address.parse(':target'))
    self.assert_address('a/b', 'target', Address.parse(':target', relative_to='a/b'))


class BuildFileAddressTest(BaseAddressTest):
  def test_build_file_forms(self):
    with self.workspace('a/b/c/BUILD') as root_dir:
      build_file = BuildFile(FileSystemProjectTree(root_dir), relpath='a/b/c/BUILD')
      self.assert_address('a/b/c', 'c', BuildFileAddress(build_file=build_file))
      self.assert_address('a/b/c', 'foo', BuildFileAddress(build_file=build_file, target_name='foo'))
      self.assertEqual('a/b/c:foo', BuildFileAddress(build_file=build_file, target_name='foo').spec)

    with self.workspace('BUILD') as root_dir:
      build_file = BuildFile(FileSystemProjectTree(root_dir), relpath='BUILD')
      self.assert_address('', 'foo', BuildFileAddress(build_file=build_file, target_name='foo'))
      self.assertEqual('//:foo', BuildFileAddress(build_file=build_file, target_name='foo').spec)
