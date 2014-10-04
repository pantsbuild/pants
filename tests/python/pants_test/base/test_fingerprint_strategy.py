# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.base.fingerprint_strategy import DefaultFingerprintStrategy
from pants_test.base_test import BaseTest


class FingerprintStrategyTest(BaseTest):
  def test_subclass_equality(self):
    class FPStrategyA(DefaultFingerprintStrategy): pass
    class FPStrategyB(DefaultFingerprintStrategy): pass

    self.assertNotEqual(FPStrategyA(), DefaultFingerprintStrategy())
    self.assertNotEqual(FPStrategyA(), FPStrategyB())
    self.assertEqual(FPStrategyA(), FPStrategyA())

    self.assertNotEqual(hash(FPStrategyA()), hash(DefaultFingerprintStrategy()))
    self.assertNotEqual(hash(FPStrategyA()), hash(FPStrategyB()))
    self.assertEqual(hash(FPStrategyA()), hash(FPStrategyA()))
