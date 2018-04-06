# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import hashlib

from pants.base.fingerprint_strategy import FingerprintStrategy
from pants.contrib.go.targets.go_binary import GoBinary


class GoBinaryFingerprintStrategy(FingerprintStrategy):
  """Build flags aware fingerprint strategy.

  This enables support for runtime merging of build flags (e.g.: config file, per-target, CLI),
  which impact the output binary.
  """

  def __init__(self, build_flags_from_option, is_flagged, get_build_flags):
    """
    :param string build_flags_from_option: Runtime value of GoCompile build_flags option.
    :param bool is_flagged: If build_flags was set via the command-line flag.
    :param func get_build_flags: Function that merges build_flags from the various sources.
    """
    self._build_flags_from_option = build_flags_from_option
    self._is_flagged = is_flagged
    self._get_build_flags = get_build_flags

  def compute_fingerprint(self, target):
    fp = target.payload.fingerprint()
    if not isinstance(target, GoBinary):
      return fp

    hasher = hashlib.sha1()
    hasher.update(fp)
    hasher.update(str(self._get_build_flags(target,
                                            self._build_flags_from_option,
                                            self._is_flagged)))
    return hasher.hexdigest()

  def __hash__(self):
    return hash((type(self), self._build_flags_from_option, self._is_flagged))

  def __eq__(self, other):
    return type(self) == type(other) and \
           self._build_flags_from_option == other._build_flags_from_option and \
           self._is_flagged == other._is_flagged
