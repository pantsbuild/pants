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

from collections import defaultdict

from twitter.common.lang import Compatibility
from twitter.pants.base.build_environment import get_buildroot
from twitter.pants.base import Target
from twitter.pants.targets.sources import SourceRoot


class TargetWithSources(Target):
  _source_to_targets = defaultdict(set)

  @classmethod
  def register_source(cls, source, target):
    cls._source_to_targets[source].add(target)

  def __init__(self, name, sources=None, exclusives=None):
    Target.__init__(self, name, exclusives=exclusives)

    self.add_labels('sources')
    self.target_base = SourceRoot.find(self)
    self._unresolved_sources = sources or []
    self._resolved_sources = None

  def expand_files(self, recursive=True, include_buildfile=True):
    """Expand files used to build this target to absolute paths.  By default this expansion is done
    recursively and target BUILD files are included.
    """

    files = []

    def _expand(target):
      files.extend([os.path.abspath(os.path.join(target.target_base, s))
          for s in (target.sources or [])])
      if include_buildfile:
        files.append(target.address.buildfile.full_path)
      if recursive:
        for dep in target.dependencies:
          if isinstance(dep, TargetWithSources):
            _expand(dep)
          elif hasattr(dep, 'address'):
            # Don't know what it is, but we'll include the BUILD file to be paranoid
            files.append(dep.address.buildfile.full_path)

    _expand(self)
    return files

  @property
  def sources(self):
    if self._resolved_sources is None:
      self._resolved_sources = self._resolve_paths(self._unresolved_sources or [])
    return self._resolved_sources

  def set_resolved_sources(self, sources):
    """Set resolved sources directly, skipping the resolution.

    Useful when synthesizing targets.
    """
    self._resolved_sources = sources

  def _resolve_paths(self, paths):
    """Resolves paths."""
    if not paths:
      return []

    def flatten_paths(*items):
      """Flattens one or more items into a list.

      If the item is iterable each of its items is flattened.  If an item is callable, it is called
      and the result is flattened.  Otherwise the atom is appended to the flattened list.  These
      rules are applied recursively such that the returned list will only contain non-iterable,
      non-callable atoms.
      """

      flat = []

      def flatmap(item):
        if isinstance(item, Compatibility.string):
          flat.append(item)
        else:
          try:
            for i in iter(item):
              flatmap(i)
          except TypeError:
            if callable(item):
              flatmap(item())
            else:
              flat.append(item)

      for item in items:
        flatmap(item)

      return flat

    src_relpath = os.path.relpath(self.address.buildfile.parent_path,
                                  os.path.join(get_buildroot(), self.target_base))

    return [os.path.normpath(os.path.join(src_relpath, path)) for path in flatten_paths(paths)]
