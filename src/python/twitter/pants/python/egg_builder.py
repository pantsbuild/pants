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

__author__ = 'Benjy Weinberger'

import glob
import os
import subprocess
import sys
from twitter.common.contextutil import environment_as, pushd

class EggBuilder(object):
  """A helper class to create an egg."""

  class EggBuildingException(Exception): pass

  def __init__(self):
    pass

  def build_egg(self, egg_root, target):
    """Build an egg containing the files at egg_root for the specified target.
    There must be an egg_root/setup.py file."""
    # TODO(Brian Wickman): Do a sanity check somewhere to ensure that
    # setuptools is on the path?
    args = [
      sys.executable,
      'setup.py', 'bdist_egg',
      '--dist-dir=dist',
      '--bdist-dir=build.%s' % target.name]
    with pushd(egg_root):
      print 'EggBuilder executing: %s' % ' '.join(args)
      with environment_as(PYTHONPATH = ':'.join(sys.path)):
        po = subprocess.Popen(args, stderr=subprocess.PIPE, stdout=subprocess.PIPE)
        rv = po.wait()
      eggs = os.path.abspath(os.path.join('dist', '*.egg'))
      eggs = glob.glob(eggs)
      if rv != 0 or len(eggs) != 1:
        comm = po.communicate()
        print >> sys.stderr, 'egg generation failed (return value=%d, num eggs=%d)' % (
          rv, len(eggs))
        print >> sys.stderr, 'STDOUT'
        print >> sys.stderr, comm[0]
        print >> sys.stderr, 'STDERR'
        print >> sys.stderr, comm[1]
        raise EggBuilder.EggBuildingException(
          'Generation of eggs failed for target = %s' % target)
      egg_path = eggs[0]
    return egg_path
