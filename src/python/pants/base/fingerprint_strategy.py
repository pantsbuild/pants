# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
from abc import abstractmethod

from pants.util.meta import AbstractClass


logger = logging.getLogger(__name__)


class StatelessFingerprintHashingMixin(object):
  """Definitions for `__hash__` and `__eq__` when a fingerprint strategy uses no stored state.

  Warning: Don't use this when the mixed in class has instance attributes mixed into its
  fingerprints _and_ the mixed in class will be used by more than one task type. This will cause
  subtle bugs because fingerprints are cached on the `Target` base class, and the cache key is the
  instance of the `FingerprintStrategy`.
  """

  def __hash__(self):
    return hash(type(self))

  def __eq__(self, other):
    return type(self) == type(other)


class UnsharedFingerprintHashingMixin(object):
  """Definitions for `__hash__` and `__eq__` when a fingerprint strategy is used by only one task.

  Warning: Don't use this when the mixed in class will be used by more than one `Task.invalidated`
  call per-run - generally this means in more than one than one task type.
  """

  def __hash__(self):
    return object.__hash__(self)

  def __eq__(self, other):
    return object.__eq__(self, other)


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

  def direct(self, target):
    return False

  def dependencies(self, target):
    return target.dependencies

  def __hash__(self):
    """Subclasses must implement a hash so computed fingerprints can be safely memoized."""

  def __eq__(self, other):
    """Subclasses must implement an equality check so computed fingerprints can be safely memoized.

    It is correct, but suboptimal, for fingerprint strategies that will produce the same results for
    any `Target` to be unequal. It is incorrect for fingerprint strategies that will produce
    different results for the same `Target` to be equal. Consider mixing in either
    `StatelessFingerprintHashingMixin` or `UnsharedFingerprintHashingMixin` before providing your
    own implementation.
    """


class DefaultFingerprintStrategy(StatelessFingerprintHashingMixin, FingerprintStrategy):
  """The default `FingerprintStrategy`, which delegates to `target.payload.invalidation_hash()`.

  :API: public
  """

  def compute_fingerprint(self, target):
    """
    :API: public
    """
    return target.payload.fingerprint()
