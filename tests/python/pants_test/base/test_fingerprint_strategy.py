# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.base.fingerprint_strategy import DefaultFingerprintStrategy
from pants.testutil.test_base import TestBase


class FingerprintStrategyTest(TestBase):
    def test_subclass_equality(self):
        class FPStrategyA(DefaultFingerprintStrategy):
            pass

        class FPStrategyB(DefaultFingerprintStrategy):
            pass

        self.assertNotEqual(FPStrategyA(), DefaultFingerprintStrategy())
        self.assertNotEqual(FPStrategyA(), FPStrategyB())
        self.assertEqual(FPStrategyA(), FPStrategyA())

        self.assertNotEqual(hash(FPStrategyA()), hash(DefaultFingerprintStrategy()))
        self.assertNotEqual(hash(FPStrategyA()), hash(FPStrategyB()))
        self.assertEqual(hash(FPStrategyA()), hash(FPStrategyA()))
