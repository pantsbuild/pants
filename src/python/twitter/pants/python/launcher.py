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
import sys
import glob
import subprocess

from twitter.common.collections import OrderedSet
from twitter.pants.python.eggparser import EggParser

class Launcher(object):
  def __init__(self, dir, binary=None):
    self._dir = dir
    self._binary = binary
    self._path = OrderedSet([os.path.abspath(self._dir)])
    self._init()

  @staticmethod
  def _setup_eggs(path, eggs):
    eggparser = EggParser()
    for egg in eggs:
      egg_file = os.path.basename(egg)
      if eggparser.is_compatible(egg_file):
        path.add(egg)

  def _init(self):
    depdir = os.path.abspath(os.path.join(os.path.abspath(self._dir), '.deps'))
    Launcher._setup_eggs(self._path, glob.glob(os.path.join(depdir, '*.egg')))

  def run(self, binary=None, interpreter_args=[], args=[], extra_deps=[], with_chroot=False):
    path = OrderedSet(self._path)
    Launcher._setup_eggs(path, extra_deps)

    if os.getenv('PANTS_NO_SITE'):
      cmdline = [sys.executable, '-S'] + interpreter_args
    else:
      cmdline = [sys.executable] + interpreter_args
    bin = binary
    if not bin: bin = self._binary
    if bin:
      cmdline.append(bin)
    if args:
      cmdline.extend(args)

    cwd = os.getcwd()
    oldenv = os.getenv('PYTHONPATH')
    os.putenv('PYTHONPATH', ':'.join(path))
    if with_chroot:
      os.chdir(self._dir)

    print 'Executing PYTHONPATH=%s %s' % (
      ':'.join(path), ' '.join(cmdline))
    po = subprocess.Popen(cmdline)
    rv = po.wait()

    if with_chroot:
      os.chdir(cwd)

    if oldenv:
      os.putenv('PYTHONPATH', oldenv)
    else:
      os.unsetenv('PYTHONPATH')

    return rv

if __name__ == '__main__':
  args = sys.argv[1:]
  if len(args) == 1:
    launcher = Launcher(args[0])
    sys.exit(launcher.run())
  elif len(args) > 1:
    launcher = Launcher(args[0], args[1])
    sys.exit(launcher.run(args=args[2:]))
  else:
    print >> sys.stderr, 'Usage: %s directory [binary.py [args]]' % sys.argv[0]
    sys.exit(1)
