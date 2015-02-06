# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import hashlib

from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.base.fingerprint_strategy import FingerprintStrategy
from pants.base.hash_utils import hash_all


class JvmFingerprintStrategy(FingerprintStrategy):
  """A FingerprintStrategy with the addition of a list of platform data entries.

  These can be used to hold things like java version.
  """

  def __init__(self, platform_data=None):
    """
    platform_data - List of platform information, such as java version.
    Order does not matter as it will be sorted.
    """
    # TODO(pl): Encode all text to bytes, as python3 hashers do not accept non-bytes.
    self.platform_data = tuple(sorted(platform_data or []))

  def compute_fingerprint(self, target):
    target_fp = target.payload.fingerprint()

    if not isinstance(target, JvmTarget):
      return target_fp

    hasher = hashlib.sha1()
    hasher.update(target_fp)
    hasher.update(bytes(hash_all(self.platform_data)))
    return hasher.hexdigest()

  def __hash__(self):
    return hash((type(self), self.platform_data))

  def __eq__(self, other):
    return type(self) == type(other) and self.platform_data == other.platform_data
