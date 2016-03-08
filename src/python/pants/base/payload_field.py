# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import json
from abc import abstractmethod
from hashlib import sha1

from twitter.common.collections import OrderedSet

from pants.util.meta import AbstractClass


def stable_json_dumps(obj):
  return json.dumps(obj, ensure_ascii=True, allow_nan=False, sort_keys=True)


def stable_json_sha1(obj):
  """
  :API: public
  """
  return sha1(stable_json_dumps(obj)).hexdigest()


def combine_hashes(hashes):
  """A simple helper function to combine other hashes.  Sorts the hashes before rolling them in."""
  hasher = sha1()
  for h in sorted(hashes):
    hasher.update(h)
  return hasher.hexdigest()


class PayloadField(AbstractClass):
  """An immutable, hashable structure to be mixed into Payload instances.

  :API: public
  """
  _fingerprint_memo = None

  def fingerprint(self):
    """A memoized sha1 hexdigest hashing the contents of this PayloadField

    The fingerprint returns either a bytestring or None.  If the return is None, consumers of the
    fingerprint may choose to elide this PayloadField from their combined hash computation.

    :API: public
    """
    if self._fingerprint_memo is None:
      self._fingerprint_memo = self._compute_fingerprint()
    return self._fingerprint_memo

  def mark_dirty(self):
    """Invalidates the memoized fingerprint for this field.

    Exposed for testing.

    :API: public
    """
    self._fingerprint_memo = None

  @abstractmethod
  def _compute_fingerprint(self):
    """This method will be called and the result memoized for ``PayloadField.fingerprint``."""
    pass

  @property
  def value(self):
    """
    :API: public
    """
    return self


class FingerprintedMixin(object):
  """Mixin this class to make your class suitable for passing to FingerprintedField.

  :API: public
  """

  def fingerprint(self):
    """Override this method to implement a fingerprint for your class.

    :API: public

    :returns: a sha1 hexdigest hashing the contents of this structure."""
    raise NotImplementedError()


class FingerprintedField(PayloadField):
  """Use this field to fingerprint any class that mixes in FingerprintedMixin.

  The caller must ensure that the class properly implements fingerprint()
  to hash the contents of the object.

  :API: public
  """

  def __init__(self, value):
    self._value = value

  def _compute_fingerprint(self):
    return self._value.fingerprint()

  @property
  def value(self):
    return self._value


class PythonRequirementsField(frozenset, PayloadField):
  """A frozenset subclass that mixes in PayloadField.

  Must be initialized with an iterable of PythonRequirement instances.

  :API: public
  """

  def _compute_fingerprint(self):
    def fingerprint_iter():
      for req in self:
        hash_items = (
          repr(req._requirement),
          req._repository,
          req._name,
          req._use_2to3,
          req.compatibility,
        )
        yield stable_json_sha1(hash_items)
    return combine_hashes(fingerprint_iter())


class ExcludesField(OrderedSet, PayloadField):
  """An OrderedSet subclass that mixes in PayloadField.

  Must be initialized with an iterable of Excludes instances.

  :API: public
  """

  def _compute_fingerprint(self):
    return stable_json_sha1(tuple(repr(exclude) for exclude in self))


class JarsField(tuple, PayloadField):
  """A tuple subclass that mixes in PayloadField.

  Must be initialized with an iterable of JarDependency instances.

  :API: public
  """

  def _compute_fingerprint(self):
    return stable_json_sha1(tuple(jar.cache_key() for jar in self))


class PrimitiveField(PayloadField):
  """A general field for primitive types.

  As long as the contents are JSON representable, their hash can be stably inferred.

  :API: public
  """

  def __init__(self, underlying=None):
    self._underlying = underlying

  @property
  def value(self):
    return self._underlying

  def _compute_fingerprint(self):
    return stable_json_sha1(self._underlying)
