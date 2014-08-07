# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import hashlib

from pants.backend.jvm.targets.jvm_target import JvmTarget

from pants.base.fingerprint_strategy import DefaultFingerprintStrategy
from pants.base.hash_utils import hash_all


class JvmFingerprintStrategy(DefaultFingerprintStrategy):
  """A FingerprintStrategy which delegates to DefaultFingerprintStrategy
  with the addition of a list of platform data entries. These can be used to hold
  things like java version."""

  def __init__(self, platform_data=None):
    """
    platform_data - List of platform information, such as java version.
    Order does not matter as it will be sorted.
    """
    self.platform_data = platform_data or []

  @classmethod
  def name(cls):
    return 'jvm'

  def compute_fingerprint(self, target):
    super_fingerprint = super(JvmFingerprintStrategy, self).compute_fingerprint(target)

    if not isinstance(target, JvmTarget):
      return super_fingerprint

    hasher = hashlib.sha1()
    hasher.update(super_fingerprint)
    hasher.update(bytes(hash_all(sorted(self.platform_data))))
    return hasher.hexdigest()