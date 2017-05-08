# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from hashlib import sha1

from pants.base.payload_field import PayloadField
from pants.source.filespec import matches_filespec
from pants.source.source_root import SourceRootConfig
from pants.source.wrapped_globs import FilesetWithSpec
from pants.util.memo import memoized_property


class SourcesField(PayloadField):
  """A PayloadField encapsulating specified sources."""

  def __init__(self, sources, ref_address=None):
    """
    :param sources: FilesetWithSpec representing the underlying sources.
    :param ref_address: optional address spec of target that provides these sources
    """
    self._sources = self._validate_sources(sources)
    self._ref_address = ref_address

  @property
  def source_root(self):
    """:returns: the source root for these sources, or None if they're not under a source root."""
    # TODO: It's a shame that we have to access the singleton directly here, instead of getting
    # the SourceRoots instance from context, as tasks do.  In the new engine we could inject
    # this into the target, rather than have it reach out for global singletons.
    return SourceRootConfig.global_instance().get_source_roots().find_by_path(self.rel_path)

  def matches(self, path):
    return self.sources.matches(path) or matches_filespec(path, self.filespec)

  @property
  def filespec(self):
    return self.sources.filespec

  @property
  def rel_path(self):
    return self.sources.rel_root

  @property
  def sources(self):
    return self._sources

  @memoized_property
  def source_paths(self):
    return list(self.sources)

  @property
  def address(self):
    """Returns the address this sources field refers to (used by some derived classses)"""
    return self._ref_address

  def has_sources(self, extension=None):
    if not self.source_paths:
      return False
    return any(source.endswith(extension) for source in self.source_paths)

  def relative_to_buildroot(self):
    """All sources joined with their relative paths."""
    return list(self.sources.paths_from_buildroot_iter())

  def _compute_fingerprint(self):
    hasher = sha1()
    hasher.update(self.rel_path)
    hasher.update(self.sources.files_hash)
    return hasher.hexdigest()

  def _validate_sources(self, sources):
    if not isinstance(sources, FilesetWithSpec):
      raise ValueError('Expected a FilesetWithSpec. `sources` should be '
                       'instantiated via `create_sources_field`.')
    return sources
