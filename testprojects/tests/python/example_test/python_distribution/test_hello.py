# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import unittest

from hello_package import hello


class HelloTest(unittest.TestCase):
    def test_hello_import(self):
        self.assertEqual("hello!", hello.hello_string())
