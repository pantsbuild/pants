# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import unittest

import six

from pants.process.pidlock import OwnerPrintingPIDLockFile


class TestOwnerPrintingPIDLockFile(unittest.TestCase):
  def setUp(self):
    self.obj = OwnerPrintingPIDLockFile('/tmp/test', False)

  def test_cmdline_for_pid(self):
    self.assertIsInstance(self.obj.cmdline_for_pid(os.getpid()), six.string_types)
