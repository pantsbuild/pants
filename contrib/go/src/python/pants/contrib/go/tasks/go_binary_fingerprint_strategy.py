# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import hashlib

from pants.base.fingerprint_strategy import FingerprintStrategy

from pants.contrib.go.targets.go_binary import GoBinary


class GoBinaryFingerprintStrategy(FingerprintStrategy):
  """Build flags aware fingerprint strategy.

  This enables support for runtime merging of build flags (e.g.: config file, per-target, CLI),
  which impact the output binary.
  """

  def __init__(self, get_build_flags_func):
    """
    :param func get_build_flags_func: Partial function that merges build_flags
    """
    self._get_build_flags_func = get_build_flags_func

  def compute_fingerprint(self, target):
    fp = target.payload.fingerprint()
    if not isinstance(target, GoBinary):
      return fp

    hasher = hashlib.sha1()
    hasher.update(fp.encode())
    hasher.update(str(self._get_build_flags_func(target)).encode())
    return hasher.hexdigest()

  def __hash__(self):
    return hash((type(self), self._get_build_flags_func))

  def __eq__(self, other):
    return type(self) == type(other) and \
        self._get_build_flags_func.args == other._get_build_flags_func.args
