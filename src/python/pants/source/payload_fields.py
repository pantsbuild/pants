# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from hashlib import sha1

from pants.base.build_environment import get_buildroot
from pants.base.payload_field import PayloadField
from pants.base.validation import assert_list
from pants.source.source_root import SourceRootConfig
from pants.source.wrapped_globs import FilesetWithSpec, matches_filespec


class SourcesField(PayloadField):
  """A PayloadField encapsulating specified sources."""

  def __init__(self, sources_rel_path, sources, ref_address=None, filespec=None):
    """
    :param sources_rel_path: path that sources parameter may be relative to
    :param sources: list of strings representing relative file paths
    :param ref_address: optional address spec of target that provides these sources
    :param filespec: glob and exclude data that generated this set of sources
    """
    self._rel_path = sources_rel_path
    self._source_paths = assert_list(sources, key_arg='sources', allowable_add=(FilesetWithSpec,))
    self._ref_address = ref_address
    self._filespec = filespec

  @property
  def source_root(self):
    """:returns: the source root for these sources, or None if they're not under a source root."""
    # TODO: It's a shame that we have to access the singleton directly here, instead of getting
    # the SourceRoots instance from context, as tasks do.  In the new engine we could inject
    # this into the target, rather than have it reach out for global singletons.
    return SourceRootConfig.global_instance().get_source_roots().find_by_path(self.rel_path)

  @property
  def filespec(self):
    return self._filespec

  def matches(self, path):
    return matches_filespec(path, self.filespec)

  @property
  def rel_path(self):
    return self._rel_path

  @property
  def source_paths(self):
    return self._source_paths

  @property
  def address(self):
    """Returns the address this sources field refers to (used by some derived classses)"""
    return self._ref_address

  @property
  def num_chunking_units(self):
    """For tasks that require chunking, this is the number of chunk units this field represents.

    By default, this is just the number of sources.  Other heuristics might consider the number
    of bytes or lines in the combined source files.
    """
    if self._source_paths:
      return len(self._source_paths)
    return 1

  def has_sources(self, extension=None):
    if not self._source_paths:
      return False
    return any(source.endswith(extension) for source in self._source_paths)

  def relative_to_buildroot(self):
    """All sources joined with ``self.rel_path``."""
    return [os.path.join(self.rel_path, source) for source in self.source_paths]

  def _compute_fingerprint(self):
    hasher = sha1()
    hasher.update(self._rel_path)
    for source in sorted(self.relative_to_buildroot()):
      hasher.update(source)
      with open(os.path.join(get_buildroot(), source), 'rb') as f:
        hasher.update(f.read())
    return hasher.hexdigest()


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
    super(DeferredSourcesField, self).__init__(sources_rel_path=None, sources=[],
                                               ref_address=ref_address)

  def populate(self, sources, rel_path=None):
    """Call this method to set the list of files represented by the target.

    Intended to be invoked by the DeferredSourcesMapper task.
    :param list sources: strings representing absolute paths of files to be included in the source set
    :param string rel_path: common prefix for files.
    """
    if self._populated:
      raise self.AlreadyPopulatedError("Called with rel_path={rel_path} sources={sources}"
      .format(rel_path=rel_path, sources=sources))
    self._rel_path = rel_path
    self._source_paths = assert_list(sources, key_arg='sources', allowable_add=(FilesetWithSpec,))
    self._populated = True

  def _validate_populated(self):
    if not self._populated:
      raise self.NotPopulatedError()

  @property
  def rel_path(self):
    self._validate_populated()
    return self._rel_path

  @property
  def source_paths(self):
    self._validate_populated()
    return self._source_paths

  def matches(self, path):
    if not self._populated:
      raise self.NotPopulatedError()
    return matches_filespec(path, self.filespec)

  def _compute_fingerprint(self):
    """A subclass must provide an implementation of _compute_fingerprint that can return a valid
    fingerprint even if the sources aren't unpacked yet.
    """
    if not self._populated:
      raise self.NotPopulatedError()
    return super(DeferredSourcesField, self)._compute_fingerprint()
