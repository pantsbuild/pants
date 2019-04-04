# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import hashlib

from future.utils import PY3
from pants.base.fingerprint_strategy import FingerprintStrategy

from pants.contrib.rust.targets.synthetic.cargo_synthetic_base import CargoSyntheticBase


class CargoFingerprintStrategy(FingerprintStrategy):

  def __init__(self, build_flags):
    self._build_flags = build_flags

  def compute_fingerprint(self, target):
    fp = target.payload.fingerprint()
    if not isinstance(target, CargoSyntheticBase):
      return fp

    hasher = hashlib.sha1()
    hasher.update(fp.encode('utf-8'))
    hasher.update(self._build_flags.encode('utf-8'))
    return hasher.hexdigest() if PY3 else hasher.hexdigest().decode('utf-8')

  def __hash__(self):
    return hash((type(self), self._build_flags.encode('utf-8')))

  def __eq__(self, other):
    return type(self) == type(other) and \
           self._build_flags == other._build_flags
