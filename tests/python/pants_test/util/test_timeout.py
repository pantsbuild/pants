# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import time
import unittest
from contextlib import contextmanager

from pants.util.timeout import Timeout


class TestTimeout(unittest.TestCase):
    def test_timeout_success(self):
        with Timeout(5):
            time.sleep(1)

    def test_timeout_failure(self):
        with self.assertRaises(KeyboardInterrupt):
            with Timeout(5):
                time.sleep(10)

    def test_timeout_none(self):
        with Timeout(None):
            time.sleep(1)

    def test_timeout_zero(self):
        with Timeout(0):
            time.sleep(1)
