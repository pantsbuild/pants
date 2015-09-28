# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import json
import os
from abc import abstractmethod
from hashlib import sha1

from twitter.common.collections import OrderedSet

from pants.backend.core import wrapped_globs
from pants.base.build_environment import get_buildroot
from pants.base.validation import assert_list
from pants.util.meta import AbstractClass


def stable_json_dumps(obj):
  return json.dumps(obj, ensure_ascii=True, allow_nan=False, sort_keys=True)


def stable_json_sha1(obj):
  return sha1(stable_json_dumps(obj)).hexdigest()


def combine_hashes(hashes):
  """A simple helper function to combine other hashes.  Sorts the hashes before rolling them in."""
  hasher = sha1()
  for h in sorted(hashes):
    hasher.update(h)
  return hasher.hexdigest()


class PayloadField(AbstractClass):
  """An immutable, hashable structure to be mixed into Payload instances."""
  _fingerprint_memo = None

  def fingerprint(self):
    """A memoized sha1 hexdigest hashing the contents of this PayloadField

    The fingerprint returns either a bytestring or None.  If the return is None, consumers of the
    fingerprint may choose to elide this PayloadField from their combined hash computation.
    """
    if self._fingerprint_memo is None:
      self._fingerprint_memo = self._compute_fingerprint()
    return self._fingerprint_memo

  @abstractmethod
  def _compute_fingerprint(self):
    """This method will be called and the result memoized for ``PayloadField.fingerprint``."""
    pass

  @property
  def value(self):
    return self


class FingerprintedMixin(object):
  """Mixin this class to make your class suitable for passing to FingerprintedField."""

  def fingerprint(self):
    """Override this method to implement a fingerprint for your class.

    :returns: a sha1 hexdigest hashing the contents of this structure."""
    raise NotImplementedError()


class FingerprintedField(PayloadField):
  """Use this field to fingerprint any class that mixes in FingerprintedMixin.

  The caller must ensure that the class properly implements fingerprint()
  to hash the contents of the object.
  """

  def __init__(self, value):
    self._value = value

  def _compute_fingerprint(self):
    return self._value.fingerprint()

  @property
  def value(self):
    return self._value


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
    self._source_paths = assert_list(sources, key_arg='sources')
    self._ref_address = ref_address
    self._filespec = filespec

  @property
  def filespec(self):
    return self._filespec

  def matches(self, path):
    return wrapped_globs.matches_filespec(path, self.filespec)

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
  """ A SourcesField that isn't populated immediately when the graph is constructed.

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
    self._source_paths = assert_list(sources, key_arg='sources')
    self._populated = True

  @property
  def source_paths(self):
    if not self._populated:
      raise self.NotPopulatedError()
    return self._source_paths

  def matches(self, path):
    if not self._populated:
      raise self.NotPopulatedError()
    return wrapped_globs.matches_filespec(path, self.filespec)

  def _compute_fingerprint(self):
    """A subclass must provide an implementation of _compute_fingerprint that can return a valid
    fingerprint even if the sources aren't unpacked yet.
    """
    if not self._populated:
      raise self.NotPopulatedError()
    return super(DeferredSourcesField, self)._compute_fingerprint()


class PythonRequirementsField(frozenset, PayloadField):
  """A frozenset subclass that mixes in PayloadField.

  Must be initialized with an iterable of PythonRequirement instances.
  """

  def _compute_fingerprint(self):
    def fingerprint_iter():
      for req in self:
        # TODO(pl): See PythonRequirement note about version_filter
        hash_items = (
          repr(req._requirement),
          req._repository,
          req._name,
          req._use_2to3,
          req.compatibility,
        )
        yield stable_json_sha1(hash_items)
    return combine_hashes(fingerprint_iter())


def hash_bundle(bundle):
  hasher = sha1()
  hasher.update(bundle._rel_path)
  for abs_path in sorted(bundle.filemap.keys()):
    buildroot_relative_path = os.path.relpath(abs_path, get_buildroot())
    hasher.update(buildroot_relative_path)
    hasher.update(bundle.filemap[abs_path])
    with open(abs_path, 'rb') as f:
      hasher.update(f.read())
  return hasher.hexdigest()


class BundleField(tuple, PayloadField):
  """A tuple subclass that mixes in PayloadField.

  Must be initialized with an iterable of Bundle instances.
  """

  def _compute_fingerprint(self):
    return combine_hashes(map(hash_bundle, self))


class ExcludesField(OrderedSet, PayloadField):
  """An OrderedSet subclass that mixes in PayloadField.

  Must be initialized with an iterable of Excludes instances.
  """

  def _compute_fingerprint(self):
    return stable_json_sha1(tuple(repr(exclude) for exclude in self))


class JarsField(tuple, PayloadField):
  """A tuple subclass that mixes in PayloadField.

  Must be initialized with an iterable of JarDependency instances.
  """

  def _compute_fingerprint(self):
    return stable_json_sha1(tuple(jar.cache_key() for jar in self))


class PrimitiveField(PayloadField):
  """A general field for primitive types.

  As long as the contents are JSON representable, their hash can be stably inferred.
  """

  def __init__(self, underlying=None):
    self._underlying = underlying

  @property
  def value(self):
    return self._underlying

  def _compute_fingerprint(self):
    return stable_json_sha1(self._underlying)
