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

import os
import tempfile
import time

from twitter.common.python.interpreter import PythonInterpreter
from twitter.common.python.pex_builder import PEXBuilder

from twitter.pants.base.config import Config
from twitter.pants.targets.python_binary import PythonBinary

from .python_chroot import PythonChroot


class PythonBinaryBuilder(object):
  class NotABinaryTargetException(Exception):
    pass

  def __init__(self, target, root_dir, run_tracker, interpreter=None, conn_timeout=None):
    self.target = target
    self.interpreter = interpreter or PythonInterpreter.get()
    if not isinstance(target, PythonBinary):
      raise PythonBinaryBuilder.NotABinaryTargetException(
          "Target %s is not a PythonBinary!" % target)

    config = Config.load()
    self.distdir = config.getdefault('pants_distdir')
    distpath = tempfile.mktemp(dir=self.distdir, prefix=target.name)

    run_info = run_tracker.run_info
    build_properties = {}
    build_properties.update(run_info.add_basic_info(run_id=None, timestamp=time.time()))
    build_properties.update(run_info.add_scm_info())

    pexinfo = target.pexinfo.copy()
    pexinfo.build_properties = build_properties
    builder = PEXBuilder(distpath, pex_info=pexinfo, interpreter=self.interpreter)

    self.chroot = PythonChroot(
        target,
        root_dir,
        builder=builder,
        interpreter=self.interpreter,
        conn_timeout=conn_timeout)

  def run(self):
    print('Building PythonBinary %s:' % self.target)
    env = self.chroot.dump()
    filename = os.path.join(self.distdir, '%s.pex' % self.target.name)
    env.build(filename)
    print('Wrote %s' % filename)
    return 0
