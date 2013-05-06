# ==================================================================================================
# Copyright 2013 Twitter, Inc.
# --------------------------------------------------------------------------------------------------
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this work except in compliance with the License.
# You may obtain a copy of the License in the LICENSE file, or at:
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==================================================================================================

import os
import os.path
import pytest
import unittest

from contextlib import contextmanager

from twitter.common.contextutil import temporary_dir, pushd
from twitter.common.dirutil import touch
from twitter.pants import set_buildroot

from twitter.pants.base import Address

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
