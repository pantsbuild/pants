# ==================================================================================================
# Copyright 2012 Twitter, Inc.
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

__author__ = 'John Sirois'

import os

from collections import defaultdict

from twitter.common.collections import OrderedSet
from twitter.pants import get_buildroot
from twitter.pants.base import ParseContext

class SourceRoot(object):
  """
    Allows registration of a source root for a set of targets.

    A source root is the base path sources for a particular language are found relative to.
    Generally compilers or interpreters for the source will expect sources relative to a base path
    and a source root allows calculation of the correct relative paths.

    It is illegal to have nested source roots.
  """

  _ROOTS = defaultdict(OrderedSet)
  _SEARCHED = set()

  @staticmethod
  def _register(sourceroot):
    for t in sourceroot.types:
      SourceRoot._ROOTS[t].add(sourceroot.basedir)

  @staticmethod
  def find(target):
    """
      Finds the source root for the given target target.  If none is registered, the parent
      directory of the target's BUILD file is returned.
    """
    target_path = os.path.relpath(target.address.buildfile.parent_path, get_buildroot())

    def _find():
      for typ in target.__class__.mro():
        for root in SourceRoot._ROOTS.get(typ, ()):
          if target_path.startswith(root):
            return root

    # Try already registered roots
    root = _find()
    if root:
      return root

    # Fall back to searching the ancestor path for a root
    for buildfile in reversed(target.address.buildfile.ancestors()):
      if buildfile not in SourceRoot._SEARCHED:
        SourceRoot._SEARCHED.add(buildfile)
        ParseContext(buildfile).parse()
        root = _find()
        if root:
          return root

    # Finally, resolve files relative to the BUILD file parent dir as the target base
    return target_path

  @staticmethod
  def here(*types):
    """Registers the cwd as a source root for the given target types."""
    return SourceRoot.register(None, *types)

  @staticmethod
  def register(basedir, *types):
    """Registers the given basedir as a source root for the given target types."""
    return SourceRoot(basedir, *types)

  def __init__(self, basedir, *types):
    """
      :basedir The base directory to resolve sources relative to
      :types The target types to register :basedir: as a source root for
    """
    basepath = os.path.abspath(basedir or os.path.curdir)
    if get_buildroot() != os.path.commonprefix((basepath, get_buildroot())):
      raise ValueError('The supplied basedir %s is not a sub-path of the project root %s' % (
        basepath,
        get_buildroot()
      ))

    self.basedir = os.path.relpath(basepath, get_buildroot())
    self.types = types
    SourceRoot._register(self)
