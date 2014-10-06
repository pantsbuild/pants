# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from abc import abstractmethod
from twitter.common.lang import AbstractClass


class FingerprintStrategy(AbstractClass):
  """A helper object for doing per-task, finer grained invalidation of Targets."""

  @abstractmethod
  def compute_fingerprint(self, target):
    """Subclasses override this method to actually compute the Task specific fingerprint."""

  def fingerprint_target(self, target):
    """Consumers of subclass instances call this to get a fingerprint labeled with the name"""
    return '{fingerprint}-{name}'.format(fingerprint=self.compute_fingerprint(target),
                                         name=type(self).__name__)

  @abstractmethod
  def __hash__(self):
    """Subclasses must implement a hash so computed fingerprints can be safely memoized."""

  @abstractmethod
  def __eq__(self):
    """Subclasses must implement an equality check so computed fingerprints can be safely memoized."""


class DefaultFingerprintStrategy(FingerprintStrategy):
  """The default FingerprintStrategy, which delegates to target.payload.invalidation_hash()."""

  def compute_fingerprint(self, target):
    return target.payload.fingerprint()

  def __hash__(self):
    return hash(type(self))

  def __eq__(self, other):
    return type(self) == type(other)
