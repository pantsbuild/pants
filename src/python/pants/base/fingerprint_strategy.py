# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import hashlib
from abc import abstractmethod

from pants.util.meta import AbstractClass


class DefaultFingerprintHashingMixin(object):
  """Default definitions for __hash__ and __eq__.

  Warning: Don't use this when the mixed in class has instance attributes mixed into its
  fingerprints.  This will cause subtle bugs because fingerprints are cached on the Target
  base class, and the cache key is the instance of the FingerprintStrategy.
  """

  def __hash__(self):
    return hash(type(self))

  def __eq__(self, other):
    return type(self) == type(other)


class FingerprintStrategy(AbstractClass):
  """A helper object for doing per-task, finer grained invalidation of Targets."""

  @abstractmethod
  def compute_fingerprint(self, target):
    """Subclasses override this method to actually compute the Task specific fingerprint."""

  def fingerprint_target(self, target):
    """Consumers of subclass instances call this to get a fingerprint labeled with the name"""
    fingerprint = self.compute_fingerprint(target)
    if fingerprint:
      return '{fingerprint}-{name}'.format(fingerprint=fingerprint, name=type(self).__name__)
    else:
      return None

  @abstractmethod
  def __hash__(self):
    """Subclasses must implement a hash so computed fingerprints can be safely memoized."""

  @abstractmethod
  def __eq__(self):
    """Subclasses must implement an equality check so computed fingerprints can be safely memoized."""


class DefaultFingerprintStrategy(DefaultFingerprintHashingMixin, FingerprintStrategy):
  """The default FingerprintStrategy, which delegates to target.payload.invalidation_hash()."""

  def compute_fingerprint(self, target):
    return target.payload.fingerprint()


class TaskIdentityFingerprintStrategy(FingerprintStrategy):
  """Fingerprint strategy which includes the current task fingerprint when fingerprinting target."""

  def __init__(self, task):
    self._task = task

  def _build_hasher(self, target):
    hasher = hashlib.sha1()
    hasher.update(target.payload.fingerprint() or '')
    hasher.update(self._task.fingerprint or '')
    return hasher

  def compute_fingerprint(self, target):
    hasher = self._build_hasher(target)
    return hasher.hexdigest()

  def __hash__(self):
    return hash(self._task.fingerprint)

  def __eq__(self, other):
    return self._task.fingerprint == other._task.fingerprint
