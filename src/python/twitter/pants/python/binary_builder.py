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
import shutil
import zipfile
import pkgutil

from twitter.pants.targets import PythonLibrary, PythonEgg, PythonBinary
from twitter.pants.python.python_chroot import PythonChroot
from twitter.pants.python.pex_creator import PexCreator

class PythonBinaryBuilder(object):
  class NotABinaryTargetException(Exception): pass

  def __init__(self, target, args, root_dir):
    self.target = target
    if not isinstance(target, PythonBinary):
      raise PythonBinaryBuilder.NotABinaryTargetException(
        "Target %s is not a PythonBinary!" % target)
    self.chroot = PythonChroot(target, root_dir)
    self.distdir = os.path.join(root_dir, 'dist')

  def _generate_zip(self):
    chroot = self.chroot.dump()
    zp_path = os.path.join(self.distdir, '%s.zip' % self.target.name)
    zippy = zipfile.ZipFile(zp_path, 'w', compression = zipfile.ZIP_DEFLATED)
    sorted_digest = list(chroot.files())
    sorted_digest.sort()
    for pth in sorted_digest:
      zippy.write(os.path.join(chroot.path(), pth), pth)
    zippy.close()
    return zp_path

  def run(self):
    print 'Building PythonBinary %s:' % self.target

    zp_path = self._generate_zip()
    print 'generated zip binary in: %s' % zp_path

    pexer = PexCreator(zp_path, self.target.name)
    pex = pexer.build(os.path.join(self.distdir, '%s.pex' % self.target.name))

    print 'generated pex binary in: %s' % pex

    return 0
