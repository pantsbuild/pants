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

from tempfile import mkdtemp

from twitter.common.dirutil import safe_open, safe_rmtree, safe_mkdir

from twitter.pants.base import Address, Target
from twitter.pants.base.build_environment import set_buildroot


class BuildRootTest(unittest.TestCase):
  """A baseclass useful for tests requiring a temporary buildroot."""

  @classmethod
  def build_path(cls, relpath):
    """Returns the canonical BUILD file path for the given relative build path."""
    if os.path.basename(relpath).startswith('BUILD'):
      return relpath
    else:
      return os.path.join(relpath, 'BUILD')

  @classmethod
  def create_dir(cls, relpath):
    """Creates a directory under the buildroot.

    relpath: The relative path to the directory from the build root.
    """
    safe_mkdir(os.path.join(cls.build_root, relpath))

  @classmethod
  def create_file(cls, relpath, contents, mode='w'):
    """Writes to a file under the buildroot.

    relpath: The relative path to the file from the build root.
    target: A string containing the contents of the file.
    mode:   the mode to write to the file in - over-write by default.
    """
    with safe_open(os.path.join(cls.build_root, relpath), mode=mode) as fp:
      fp.write(contents)

  @classmethod
  def create_target(cls, relpath, target):
    """Adds the given target specification to the BUILD file at relpath.

    relpath: The relative path to the BUILD file from the build root.
    target:  A string containing the target definition as it would appear in a BUILD file.
    """
    cls.create_file(cls.build_path(relpath), target, mode='a')

  @classmethod
  def setUpClass(cls):
    cls.build_root = mkdtemp(suffix='_BUILD_ROOT')
    set_buildroot(cls.build_root)
    cls._cwd = os.getcwd()
    os.chdir(cls.build_root)
    Target._clear_all_addresses()

  @classmethod
  def tearDownClass(cls):
    os.chdir(cls._cwd)
    safe_rmtree(cls.build_root)

  @classmethod
  def target(cls, address):
    """Resolves the given target address to a Target object.

    address: The BUILD target address to resolve.

    Returns the corresponding Target or else None if the address does not point to a defined Target.
    """
    return Target.get(Address.parse(cls.build_root, address, is_relative=False))
