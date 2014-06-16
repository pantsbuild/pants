# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
import unittest
from contextlib import contextmanager

import pytest
from twitter.common.contextutil import pushd, temporary_dir
from twitter.common.dirutil import touch

from pants.base.address import BuildFileAddress, SyntheticAddress, parse_spec
from pants.base.build_file import BuildFile
from pants.base.build_root import BuildRoot


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
    self.assertAddress('a/b', 'b', SyntheticAddress.parse('a/b'))
    self.assertAddress('a/b', 'target', SyntheticAddress.parse(':target', 'a/b'))
    self.assertAddress('', 'target', SyntheticAddress.parse(':target'))

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

  def test_parse_spec(self):
    spec_path, target_name = parse_spec('a/b/c/')
    self.assertEqual(spec_path, 'a/b/c')
    self.assertEqual(target_name, 'c')

    spec_path, target_name = parse_spec('a/b/c')
    self.assertEqual(spec_path, 'a/b/c')
    self.assertEqual(target_name, 'c')

    spec_path, target_name = parse_spec('a/b/c:foo')
    self.assertEqual(spec_path, 'a/b/c')
    self.assertEqual(target_name, 'foo')


  # TODO(pl): Convert these old tests to use new Address object, hit the relative_to codepath
  # and parse_spec.  In practice these are so thoroughly covered by actual usage in the codebase
  # that I'm confident for now punting further tests to a fast follow.

  # def test_full_forms(self):
  #   with self.workspace('a/BUILD') as root_dir:
  #     self.assertAddress(root_dir, 'a/BUILD', 'b', Address.parse(root_dir, 'a:b'))
  #     self.assertAddress(root_dir, 'a/BUILD', 'b', Address.parse(root_dir, 'a/:b'))
  #     self.assertAddress(root_dir, 'a/BUILD', 'b', Address.parse(root_dir, 'a/BUILD:b'))
  #     self.assertAddress(root_dir, 'a/BUILD', 'b', Address.parse(root_dir, 'a/BUILD/:b'))

  # def test_default_form(self):
  #   with self.workspace('a/BUILD') as root_dir:
  #     self.assertAddress(root_dir, 'a/BUILD', 'a', Address.parse(root_dir, 'a'))
  #     self.assertAddress(root_dir, 'a/BUILD', 'a', Address.parse(root_dir, 'a/BUILD'))
  #     self.assertAddress(root_dir, 'a/BUILD', 'a', Address.parse(root_dir, 'a/BUILD/'))

  # def test_top_level(self):
  #   with self.workspace('BUILD') as root_dir:
  #     self.assertAddress(root_dir, 'BUILD', 'c', Address.parse(root_dir, ':c'))
  #     self.assertAddress(root_dir, 'BUILD', 'c', Address.parse(root_dir, '.:c'))
  #     self.assertAddress(root_dir, 'BUILD', 'c', Address.parse(root_dir, './:c'))
  #     self.assertAddress(root_dir, 'BUILD', 'c', Address.parse(root_dir, './BUILD:c'))
  #     self.assertAddress(root_dir, 'BUILD', 'c', Address.parse(root_dir, 'BUILD:c'))

  # def test_parse_from_root_dir(self):
  #   with self.workspace('a/b/c/BUILD') as root_dir:
  #     self.assertAddress(root_dir, 'a/b/c/BUILD', 'c',
  #                        Address.parse(root_dir, 'a/b/c', is_relative=False))
  #     self.assertAddress(root_dir, 'a/b/c/BUILD', 'c',
  #                        Address.parse(root_dir, 'a/b/c', is_relative=True))

  # def test_parse_from_sub_dir(self):
  #   with self.workspace('a/b/c/BUILD') as root_dir:
  #     with pushd(os.path.join(root_dir, 'a')):
  #       self.assertAddress(root_dir, 'a/b/c/BUILD', 'c',
  #                          Address.parse(root_dir, 'b/c', is_relative=True))

  #       with pytest.raises(IOError):
  #         Address.parse(root_dir, 'b/c', is_relative=False)
