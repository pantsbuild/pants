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

from pants.base.address import Address
from pants.base.build_environment import set_buildroot


class AddressTest(unittest.TestCase):
  @contextmanager
  def workspace(self, *buildfiles):
    with temporary_dir() as root_dir:
      set_buildroot(root_dir)
      with pushd(root_dir):
        for buildfile in buildfiles:
          touch(os.path.join(root_dir, buildfile))
        yield os.path.realpath(root_dir)

  def assertAddress(self, root_dir, path, name, address):
    self.assertEqual(root_dir, address.buildfile.root_dir)
    self.assertEqual(path, address.buildfile.relpath)
    self.assertEqual(name, address.target_name)

  def test_full_forms(self):
    with self.workspace('a/BUILD') as root_dir:
      self.assertAddress(root_dir, 'a/BUILD', 'b', Address.parse(root_dir, 'a:b'))
      self.assertAddress(root_dir, 'a/BUILD', 'b', Address.parse(root_dir, 'a/:b'))
      self.assertAddress(root_dir, 'a/BUILD', 'b', Address.parse(root_dir, 'a/BUILD:b'))
      self.assertAddress(root_dir, 'a/BUILD', 'b', Address.parse(root_dir, 'a/BUILD/:b'))

  def test_default_form(self):
    with self.workspace('a/BUILD') as root_dir:
      self.assertAddress(root_dir, 'a/BUILD', 'a', Address.parse(root_dir, 'a'))
      self.assertAddress(root_dir, 'a/BUILD', 'a', Address.parse(root_dir, 'a/BUILD'))
      self.assertAddress(root_dir, 'a/BUILD', 'a', Address.parse(root_dir, 'a/BUILD/'))

  def test_top_level(self):
    with self.workspace('BUILD') as root_dir:
      self.assertAddress(root_dir, 'BUILD', 'c', Address.parse(root_dir, ':c'))
      self.assertAddress(root_dir, 'BUILD', 'c', Address.parse(root_dir, '.:c'))
      self.assertAddress(root_dir, 'BUILD', 'c', Address.parse(root_dir, './:c'))
      self.assertAddress(root_dir, 'BUILD', 'c', Address.parse(root_dir, './BUILD:c'))
      self.assertAddress(root_dir, 'BUILD', 'c', Address.parse(root_dir, 'BUILD:c'))

  def test_parse_from_root_dir(self):
    with self.workspace('a/b/c/BUILD') as root_dir:
      self.assertAddress(root_dir, 'a/b/c/BUILD', 'c',
                         Address.parse(root_dir, 'a/b/c', is_relative=False))
      self.assertAddress(root_dir, 'a/b/c/BUILD', 'c',
                         Address.parse(root_dir, 'a/b/c', is_relative=True))

  def test_parse_from_sub_dir(self):
    with self.workspace('a/b/c/BUILD') as root_dir:
      with pushd(os.path.join(root_dir, 'a')):
        self.assertAddress(root_dir, 'a/b/c/BUILD', 'c',
                           Address.parse(root_dir, 'b/c', is_relative=True))

        with pytest.raises(IOError):
          Address.parse(root_dir, 'b/c', is_relative=False)
