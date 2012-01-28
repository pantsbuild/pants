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

from twitter.common.contextutil import pushd

from twitter.pants import get_buildroot
from twitter.pants.base import Target
from twitter.pants.targets.sources import SourceRoot

class TargetWithSources(Target):
  def __init__(self, name, is_meta=False):
    Target.__init__(self, name, is_meta)

    self.target_base = SourceRoot.find(self)

  def expand_files(self, recursive=True):
    """Expand files used to build this target to absolute paths.  By default this expansion is done
    recursively."""

    files = []

    def _expand(target):
      files.extend([os.path.abspath(os.path.join(target.target_base, s))
          for s in (target.sources or [])])
      files.extend([target.address.buildfile.full_path])
      if recursive:
        for dep in target.dependencies:
          if isinstance(dep, TargetWithSources):
            _expand(dep)
          elif hasattr(dep, 'address'):
            # Don't know what it is, but we'll include the BUILD file to be paranoid
            files.append(dep.address.buildfile.full_path)

    _expand(self)
    return files

  def _resolve_paths(self, rel_base, paths):
    """
      Resolves paths relative to the given rel_base from the build root.
      For example:
        target: ~/workspace/src/java/com/twitter/common/base/BUILD
        rel_base: src/resources

      Resolves paths from:
        ~/workspace/src/resources/com/twitter/common/base
    """

    # meta targets are composed of already-resolved paths
    if not paths or self.is_meta:
      return paths

    def flatten_paths(*items):
      """Flattens one or more items into a list.  If the item is iterable each of its items is
      flattened.  If an item is callable, it is called and the result is flattened.  Otherwise the
      atom is appended to the flattened list.  These rules are applied recursively such that the
      returned list will only contain non-iterable, non-callable atoms."""

      flat = []

      def flatmap(item):
        if isinstance(item, basestring):
          flat.append(item)
        else:
          try:
            for i in iter(item):
              flatmap(i)
          except:
            if callable(item):
              flatmap(item())
            else:
              flat.append(item)

      for item in items:
        flatmap(item)

      return flat

    src_relpath = os.path.relpath(self.address.buildfile.parent_path,
                                  os.path.join(get_buildroot(), self.target_base))

    resolve_basepath = os.path.join(get_buildroot(), rel_base, src_relpath)
    with pushd(resolve_basepath):
      return [ os.path.normpath(os.path.join(src_relpath, path)) for path in flatten_paths(paths) ]
