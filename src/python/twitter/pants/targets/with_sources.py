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

from twitter.pants.base import Target

class TargetWithSources(Target):
  def __init__(self, target_base, name, is_meta = False):
    Target.__init__(self, name, is_meta)

    self.target_base = target_base

  def _resolve_paths(self, base, paths):
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

    base_path = os.path.join(self.address.buildfile.root_dir, self.target_base)
    buildfile = os.path.join(self.address.buildfile.root_dir, self.address.buildfile.relpath)
    src_relpath = os.path.dirname(buildfile).replace(base_path + '/', '')

    src_root = os.path.join(self.address.buildfile.root_dir, base)
    src_base_path = os.path.join(src_root, src_relpath)

    def resolve_path(path):
      if path.startswith('/'):
        return path[1:]
      else:
        return os.path.join(src_relpath, path)

    start = os.path.abspath(os.curdir)
    try:
      os.chdir(src_base_path)
      return [ resolve_path(path) for path in flatten_paths(paths) ]
    finally:
      os.chdir(start)
