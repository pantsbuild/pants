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
import glob
from pkg_resources import Environment

class PythonEgg(object):
  """Egg equivalence classes"""

  class AmbiguousEggNest(Exception):
    def __init__(self, glob, env):
      Exception.__init__(self, "Egg description (%s) matches multiple distributions: %s" % (
        glob, ' '.join(pkg for pkg in env)))

  class AmbiguousEggVersions(Exception):
    def __init__(self, glob):
      Exception.__init__(self, "Egg description (%s) has ambiguous versions" % glob)

  def __init__(self, egg_glob):
    """
      Construct an Egg equivalence class.

      egg_glob: A glob.glob() compatible egg pattern, e.g.:
        - Mako-0.4.0-py2.6.egg
        - ZooKeeper-0.4-*.egg
        - ZooKeeper*
        - *.egg

      All eggs in the pattern must be the same package/version, but may
      differ on platform.  This is how we support creating "fat" pex
      binaries, by packaging the same egg but with native code compiled for
      several architectures, e.g. linux-x86_64 and macosx-10.6-x86_64.
    """
    # architecture inspecific platform so we can do fat pexes
    self._env = Environment(search_path = glob.glob(egg_glob), platform = None)
    pkgs = [pkg for pkg in self._env]
    if len(pkgs) != 1:
      raise PythonEgg.AmbiguousEggNest(egg_glob, self._env)
    self.name = pkgs[0]

    # all eggs should either be versioned or all unversioned
    # similarly, if they all have versions, they should all be the same
    vers_defined = set(pkg.has_version() for pkg in self._env[self.name])
    vers = set([pkg.version for pkg in self._env[self.name] if pkg.has_version()])
    if len(vers) > 1 or len(vers_defined) != 1:
      raise PythonEgg.AmbiguousEggVersions(egg_glob)

    self.eggs = [egg.location for egg in self._env[self.name]]

  def resolve(self):
    yield self

  def __repr__(self):
    return 'Egg(%s @ %s)' % (self.name, '+'.join(os.path.relpath(egg) for egg in self.eggs))
