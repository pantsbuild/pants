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

from __future__ import print_function

__author__ = 'Brian Wickman'

import os
import tempfile

from twitter.common.python.pex_builder import PEXBuilder
from twitter.pants.base import Config
from twitter.pants.targets import PythonBinary
from twitter.pants.python.python_chroot import PythonChroot

class PythonBinaryBuilder(object):
  class NotABinaryTargetException(Exception): pass

  def __init__(self, target, args, root_dir, conn_timeout=None):
    self.target = target
    if not isinstance(target, PythonBinary):
      raise PythonBinaryBuilder.NotABinaryTargetException(
        "Target %s is not a PythonBinary!" % target)
    config = Config.load()
    self.distdir = config.getdefault('pants_distdir')
    distpath = tempfile.mktemp(dir=self.distdir, prefix=target.name)
    self.builder = PEXBuilder(distpath)

    # configure builder PexInfo options
    for repo in target._repositories:
      self.builder.info().add_repository(repo)
    for index in target._indices:
      self.builder.info().add_index(index)
    self.builder.info().allow_pypi = target._allow_pypi
    self.builder.info().zip_safe = target._zip_safe
    self.builder.info().inherit_path = target._inherit_path
    self.builder.info().entry_point = target._entry_point
    self.builder.info().ignore_errors = target._ignore_errors

    self.chroot = PythonChroot(target, root_dir, builder=self.builder, conn_timeout=conn_timeout)

  def run(self):
    print('Building PythonBinary %s:' % self.target)
    env = self.chroot.dump()
    filename = os.path.join(self.distdir, '%s.pex' % self.target.name)
    env.build(filename)
    print('Wrote %s' % filename)
    return 0
