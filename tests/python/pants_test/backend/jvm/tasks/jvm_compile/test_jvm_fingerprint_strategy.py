# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.backend.jvm.tasks.jvm_compile.jvm_fingerprint_strategy import JvmFingerprintStrategy
from pants_test.base_test import BaseTest


class JvmFingerprintStrategyTest(BaseTest):
  def test_platform_data_differs_from_no_data(self):
    # Pass in platform data, could be java versions for example.
    a = self.make_target(':a', target_type=JvmTarget, dependencies=[])
    fingerprinter_no_data = JvmFingerprintStrategy()
    fingerprinter_data = JvmFingerprintStrategy(['test'])
    hash_no_data = fingerprinter_no_data.compute_fingerprint(a)
    hash_data = fingerprinter_data.compute_fingerprint(a)
    self.assertNotEquals(hash_no_data, hash_data)

  def test_use_default_for_non_jvm_target(self):
    # Not a jvm target, so we will not do the extra hashing
    a = self.make_target(':a', dependencies=[])
    fingerprinter_no_data = JvmFingerprintStrategy()
    fingerprinter_data = JvmFingerprintStrategy(['test'])
    hash_no_extra = fingerprinter_no_data.compute_fingerprint(a)
    hash_extra = fingerprinter_data.compute_fingerprint(a)
    self.assertEquals(hash_no_extra, hash_extra)

  def test_hashing_and_equality(self):
    self.assertEqual(
      JvmFingerprintStrategy(),
      JvmFingerprintStrategy(),
    )
    self.assertEqual(
      hash(JvmFingerprintStrategy()),
      hash(JvmFingerprintStrategy()),
    )

    self.assertNotEqual(
      JvmFingerprintStrategy(),
      JvmFingerprintStrategy(['test']),
    )
    self.assertNotEqual(
      hash(JvmFingerprintStrategy()),
      hash(JvmFingerprintStrategy(['test'])),
    )

    self.assertEqual(
      JvmFingerprintStrategy(['test']),
      JvmFingerprintStrategy(('test',)),
    )
    self.assertEqual(
      hash(JvmFingerprintStrategy(['test'])),
      hash(JvmFingerprintStrategy(('test',))),
    )

    self.assertEqual(
      JvmFingerprintStrategy(['a', 'b']),
      JvmFingerprintStrategy(['b', 'a']),
    )
    self.assertEqual(
      hash(JvmFingerprintStrategy(['a', 'b'])),
      hash(JvmFingerprintStrategy(['b', 'a'])),
    )
