# ==================================================================================================
# Copyright 2011 Twitter, Inc.
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
import pytest

from twitter.common.python import PythonLauncher

from twitter.pants import get_buildroot, egg
from twitter.pants.base import Target, Address
from twitter.pants.targets import PythonBinary, PythonLibrary
from twitter.pants.python.python_chroot import PythonChroot

def create_eggdrop_chroot(dep):
  target = Target.get(
    Address.parse(get_buildroot(),
      'tests/python/twitter/pants/python/resources:%s' % dep))
  return PythonChroot(target, get_buildroot())

class PythonChrootEggsTest(unittest.TestCase):
  ZIPSAFE_EGG = 'eggdrop_soup_zipsafe_egg'
  NOT_ZIPSAFE_EGG = 'eggdrop_soup_not_zipsafe_egg'
  NOT_ZIPSAFE_EGG_DIR = 'eggdrop_soup_not_zipsafe_egg_dir'

  def test_zipsafe_egg(self):
    chroot = create_eggdrop_chroot(PythonChrootEggsTest.ZIPSAFE_EGG)
    launcher = PythonLauncher(chroot.dump().path())
    assert launcher.run() == 0

  def test_non_zipsafe_egg(self):
    chroot = create_eggdrop_chroot(PythonChrootEggsTest.NOT_ZIPSAFE_EGG)
    launcher = PythonLauncher(chroot.dump().path())
    assert launcher.run() == 0

  def test_non_zipsafe_egg_dir(self):
    chroot = create_eggdrop_chroot(PythonChrootEggsTest.NOT_ZIPSAFE_EGG_DIR)
    launcher = PythonLauncher(chroot.dump().path())
    assert launcher.run() == 0
