# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
import unittest
from contextlib import contextmanager

from twitter.common.contextutil import pushd, temporary_dir
from twitter.common.dirutil import touch

from pants.base.address import BuildFileAddress, SyntheticAddress, parse_spec
from pants.base.build_file import BuildFile
from pants.base.build_root import BuildRoot


class ParseSpecTest(unittest.TestCase):
  def test_parse_spec(self):
    spec_path, target_name = parse_spec('a/b/c/')
    self.assertEqual(spec_path, 'a/b/c')
    self.assertEqual(target_name, 'c')

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
    spec_path, target_name = parse_spec('//a/b/c/')
    self.assertEqual(spec_path, 'a/b/c')
    self.assertEqual(target_name, 'c')

    spec_path, target_name = parse_spec('//a/b/c')
    self.assertEqual(spec_path, 'a/b/c')
    self.assertEqual(target_name, 'c')

    spec_path, target_name = parse_spec('//a/b/c:c')
    self.assertEqual(spec_path, 'a/b/c')
    self.assertEqual(target_name, 'c')

    spec_path, target_name = parse_spec('//:c')
    self.assertEqual(spec_path, '')
    self.assertEqual(target_name, 'c')


class AddressTest(unittest.TestCase):
  @contextmanager
  def workspace(self, *buildfiles):
    with temporary_dir() as root_dir:
      with BuildRoot().temporary(root_dir):
        with pushd(root_dir):
          for buildfile in buildfiles:
            touch(os.path.join(root_dir, buildfile))
          yield os.path.realpath(root_dir)

  def assertAddress(self, spec_path, target_name, address):
    self.assertEqual(spec_path, address.spec_path)
    self.assertEqual(target_name, address.target_name)

  def test_synthetic_forms(self):
    self.assertAddress('a/b', 'target', SyntheticAddress.parse('a/b:target'))
    self.assertAddress('a/b', 'target', SyntheticAddress.parse('//a/b:target'))
    self.assertAddress('a/b', 'b', SyntheticAddress.parse('a/b'))
    self.assertAddress('a/b', 'b', SyntheticAddress.parse('//a/b'))
    self.assertAddress('a/b', 'target', SyntheticAddress.parse(':target', relative_to='a/b'))
    self.assertAddress('', 'target', SyntheticAddress.parse('//:target', relative_to='a/b'))
    self.assertAddress('', 'target', SyntheticAddress.parse(':target'))
    self.assertAddress('a/b', 'target', SyntheticAddress.parse(':target', relative_to='a/b'))

  def test_build_file_forms(self):
    with self.workspace('a/b/c/BUILD') as root_dir:
      build_file = BuildFile(root_dir, relpath='a/b/c')
      self.assertAddress('a/b/c', 'c', BuildFileAddress(build_file))
      self.assertAddress('a/b/c', 'foo', BuildFileAddress(build_file, target_name='foo'))
      self.assertEqual('a/b/c:foo', BuildFileAddress(build_file, target_name='foo').spec)

    with self.workspace('BUILD') as root_dir:
      build_file = BuildFile(root_dir, relpath='')
      self.assertAddress('', 'foo', BuildFileAddress(build_file, target_name='foo'))
      self.assertEqual(':foo', BuildFileAddress(build_file, target_name='foo').spec)
