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

import unittest

from twitter.common.contextutil import environment_as, pushd, temporary_dir
from twitter.common.dirutil import safe_mkdir, touch

from twitter.pants.build_root import BuildRoot


class BuildRootTest(unittest.TestCase):

  def setUp(self):
    self.original_root = BuildRoot().path
    self.new_root = BuildRoot().path + 'not_original'
    BuildRoot().reset()

  def tearDown(self):
    BuildRoot().reset()

  def test_via_env(self):
    with environment_as(PANTS_BUILD_ROOT=self.new_root):
      self.assertEqual(self.new_root, BuildRoot().path)

  def test_via_set(self):
    BuildRoot().path = self.new_root
    self.assertEqual(self.new_root, BuildRoot().path)

  def test_reset(self):
    BuildRoot().path = self.new_root
    BuildRoot().reset()
    self.assertEqual(self.original_root, BuildRoot().path)

  def test_via_pantsini(self):
    with temporary_dir() as root:
      root = os.path.realpath(root)
      touch(os.path.join(root, 'pants.ini'))
      with pushd(root):
        self.assertEqual(root, BuildRoot().path)

      BuildRoot().reset()
      child = os.path.join(root, 'one', 'two')
      safe_mkdir(child)
      with pushd(child):
        self.assertEqual(root, BuildRoot().path)

  def test_temporary(self):
    with BuildRoot().temporary(self.new_root):
      self.assertEqual(self.new_root, BuildRoot().path)
    self.assertEqual(self.original_root, BuildRoot().path)

  def test_singleton(self):
    self.assertEqual(BuildRoot().path, BuildRoot().path)
    BuildRoot().path = self.new_root
    self.assertEqual(BuildRoot().path, BuildRoot().path)
