# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
from collections import defaultdict

from twitter.common.lang import Compatibility

from pants.base.build_environment import get_buildroot
from pants.base.target import Target
from pants.targets.sources import SourceRoot


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

  def sources_relative_to_buildroot(self):
    """Returns this target's sources, relative to the buildroot.

    Prefer this over .sources unless you need to know about the target_base.
    """
    for src in self.sources:
      yield os.path.join(self.target_base, src)

  def sources_absolute_paths(self):
    """Returns the absolute paths of this target's sources.

    Prefer this over .sources unless you need to know about the target_base.
    """
    abs_target_base = os.path.join(get_buildroot(), self.target_base)
    for src in self.sources:
      yield os.path.join(abs_target_base, src)

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
