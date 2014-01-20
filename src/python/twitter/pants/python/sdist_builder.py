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

from __future__ import print_function

import glob
import os
import subprocess
import sys

from twitter.common.contextutil import pushd
from twitter.common.python.installer import Packager


class SdistBuilder(object):
  """A helper class to run setup.py projects."""

  class Error(Exception): pass
  class SetupError(Error): pass

  @classmethod
  def build(cls, setup_root, target, interpreter=None):
    packager = Packager(setup_root, interpreter=interpreter,
        install_dir=os.path.join(setup_root, 'dist'))
    try:
      return packager.sdist()
    except Packager.InstallFailure as e:
      raise cls.SetupError(str(e))
