# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from abc import abstractmethod
from twitter.common.lang import AbstractClass


class FingerprintStrategy(AbstractClass):
  """A helper object for doing per-task, finer grained invalidation of Targets."""

  @classmethod
  def name(cls):
    """The name of this strategy.

    This will ultimately appear in a human readable form in the fingerprint itself, for debugging
    purposes.
    """
    raise NotImplemented

  @abstractmethod
  def compute_fingerprint(self, target):
    """Subclasses override this method to actually compute the Task specific fingerprint."""

  def fingerprint_target(self, target):
    """Consumers of subclass instances call this to get a fingerprint labeled with the name"""
    return '{fingerprint}-{name}'.format(fingerprint=self.compute_fingerprint(target),
                                         name=self.name())


class DefaultFingerprintStrategy(FingerprintStrategy):
  """The default FingerprintStrategy, which delegates to target.payload.invalidation_hash()."""

  @classmethod
  def name(cls):
    return 'default'

  def compute_fingerprint(self, target):
    return target.payload.invalidation_hash()
