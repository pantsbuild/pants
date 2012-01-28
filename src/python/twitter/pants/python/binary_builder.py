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

__author__ = 'Brian Wickman'

import os

from twitter.common.python.pexbuilder import PexBuilder
from twitter.pants.targets import PythonBinary
from twitter.pants.python.python_chroot import PythonChroot

class PythonBinaryBuilder(object):
  class NotABinaryTargetException(Exception): pass

  def __init__(self, target, args, root_dir):
    self.target = target
    if not isinstance(target, PythonBinary):
      raise PythonBinaryBuilder.NotABinaryTargetException(
        "Target %s is not a PythonBinary!" % target)
    self.chroot = PythonChroot(target, root_dir)
    self.distdir = os.path.join(root_dir, 'dist')

  def _generate(self):
    env = self.chroot.dump()
    pex = PexBuilder(env)
    pex_name = os.path.join(self.distdir, '%s.pex' % self.target.name)
    pex.write(pex_name)
    print 'Wrote %s' % pex_name

  def run(self):
    print 'Building PythonBinary %s:' % self.target
    self._generate()
    return 0
