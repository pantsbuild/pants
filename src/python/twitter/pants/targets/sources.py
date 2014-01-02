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

import os

from functools import partial
from twitter.pants.base import ParseContext, TargetDefinitionException
from twitter.pants.base.build_environment import get_buildroot


class SourceRoot(object):
  """Allows registration of a source root for a set of targets.

  A source root is the base path sources for a particular language are found relative to.
  Generally compilers or interpreters for the source will expect sources relative to a base path
  and a source root allows calculation of the correct relative paths.

  It is illegal to have nested source roots.
  """
  _ROOTS = set()  # Paths relative to buildroot.
  _ALLOWED_TARGET_TYPES = {}  # basedir -> list of target types.
  _SEARCHED = set()

  @staticmethod
  def _register(sourceroot):
    SourceRoot._ROOTS.add(sourceroot._basedir)
    if sourceroot._allowed_target_types is not None:
      SourceRoot._ALLOWED_TARGET_TYPES[sourceroot._basedir] = sourceroot._allowed_target_types


  @staticmethod
  def find(target):
    """Finds the source root for the given target.

    If none is registered, returns the parent directory of the target's BUILD file.
    """
    target_path = os.path.relpath(target.address.buildfile.parent_path, get_buildroot())
    def _find():
      for root in SourceRoot._ROOTS:
        if target_path.startswith(root):  # The only candidate root for this target.
          # Validate the target type, if restrictions were specified.
          if root in SourceRoot._ALLOWED_TARGET_TYPES and not \
             any(map(lambda t: isinstance(target, t), SourceRoot._ALLOWED_TARGET_TYPES[root])):
            # TODO: Find a way to use the BUILD file aliases in the error message, instead
            # of target.__class__.__name__. E.g., java_tests instead of JavaTests.
            raise TargetDefinitionException(target,
              'Target type %s not allowed under %s' % (target.__class__.__name__, root))
          return root
      return None

    root = _find()
    if root:
      return root

    # Fall back to searching the ancestor path for a root.
    # TODO(benjy): Seems like an odd way to trigger evaluation of the repo layout
    # stanzas in the root-level BUILD file. Should that be eval'd up front?
    for buildfile in reversed(target.address.buildfile.ancestors()):
      if buildfile not in SourceRoot._SEARCHED:
        ParseContext(buildfile).parse()
        SourceRoot._SEARCHED.add(buildfile)
        root = _find()
        if root:
          return root

    # Fall back to the BUILD file's directory.
    return target_path

  @staticmethod
  def register(basedir):
    """Registers the given basedir as a source root for the given target types."""
    return SourceRoot(basedir)

  @classmethod
  def lazy_rel_source_root(cls, reldir):
    return partial(cls, reldir=reldir)

  def __init__(self, basedir, *allowed_target_types, **kwargs):
    """Initializes a source root at basedir for the given target types.

    :basedir The base directory to resolve sources relative to
    :allowed_target_types Optional list of target types. If specified, we enforce that
                          only targets of those types appear under this source root.
    """
    buildroot = get_buildroot()
    reldir = kwargs.pop('reldir', buildroot)  # TODO: Is this needed?
    basepath = os.path.abspath(os.path.join(reldir, basedir))
    if buildroot != os.path.commonprefix((basepath, buildroot)):
      raise ValueError('The supplied basedir %s is not a sub-path of the project root %s' % (
        basepath,
        buildroot
      ))

    self._basedir = os.path.relpath(basepath, buildroot)
    self._allowed_target_types = allowed_target_types or None
    SourceRoot._register(self)
