# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import unittest


class DummyTest(unittest.TestCase):
    def test_foo(self):
        a = 10
        b = 20
        self.assertEqual(a * 2, b)
