# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from hashlib import sha1

from pants.base.payload_field import PayloadField
from pants.source.source_root import SourceRootConfig
from pants.source.wrapped_globs import Files, FilesetWithSpec, matches_filespec
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

  @property
  def filespec(self):
    return self.sources.filespec

  def matches(self, path):
    return matches_filespec(path, self.filespec)

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
    """All sources joined with ``self.rel_path``."""
    return [os.path.join(self.rel_path, source) for source in self.source_paths]

  def _compute_fingerprint(self):
    hasher = sha1()
    hasher.update(self.rel_path)
    for source in sorted(self.source_paths):
      hasher.update(source)
      hasher.update(self.sources.file_hash(source))
    return hasher.hexdigest()

  def _validate_sources(self, sources):
    if not isinstance(sources, FilesetWithSpec):
      raise ValueError('Expected a FilesetWithSpec. `sources` should be '
                       'instantiated via `create_sources_field`.')
    return sources


class DeferredSourcesField(SourcesField):
  """A SourcesField that isn't populated immediately when the graph is constructed.

  You must subclass this and provide a fingerprint implementation. Requires a task
  to call populate() to provide its contents later during processing.  For example,
  if sources are in an archive, you might use the fingerprint of the archive. If they
  are from an external artifact, you might take a fingerprint of the name and version of
  the artifact.
  """

  class AlreadyPopulatedError(Exception):
    """Raised when a DeferredSourcesField has already been populated."""
    pass

  class NotPopulatedError(Exception):
    """ Raised when the PayloadField has not been populated yet."""

    def __init__(self):
      super(Exception, self).__init__(
        "Field requires a call to populate() before this method can be called.")

  def __init__(self, ref_address):
    self._populated = False
    super(DeferredSourcesField, self).__init__(sources=None,
                                               ref_address=ref_address)

  def populate(self, sources, rel_path):
    """Call this method to set the list of files represented by the target.

    Intended to be invoked by the DeferredSourcesMapper task.
    :param list sources: strings representing absolute paths of files to be included in the source set
    :param string rel_path: common prefix for files.
    """
    if self._populated:
      raise self.AlreadyPopulatedError("Called with rel_path={rel_path} sources={sources}"
      .format(rel_path=rel_path, sources=sources))
    self._populated = True
    sources = Files.create_fileset_with_spec(rel_path, *sources)
    self._sources = self._validate_sources(sources)

  def _validate_populated(self):
    if not self._populated:
      raise self.NotPopulatedError()

  @property
  def rel_path(self):
    self._validate_populated()
    return super(DeferredSourcesField, self).rel_path

  @property
  def sources(self):
    self._validate_populated()
    return self._sources

  def matches(self, path):
    if not self._populated:
      raise self.NotPopulatedError()
    return matches_filespec(path, self.filespec)

  def _compute_fingerprint(self):
    """A subclass must provide an implementation of _compute_fingerprint that can return a valid
    fingerprint even if the sources aren't unpacked yet.
    """
    self._validate_populated()
    return super(DeferredSourcesField, self)._compute_fingerprint()

  def _validate_sources(self, sources):
    """Override `_validate_sources` to allow None."""
    if self._populated:
      return super(DeferredSourcesField, self)._validate_sources(sources)
    return sources
