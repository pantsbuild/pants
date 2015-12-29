# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import subprocess
import unittest

from pants.util.process_handler import SubprocessProcessHandler


class TestSubprocessProcessHandler(unittest.TestCase):
  def test_exit_1(self):
    process = subprocess.Popen(["/bin/sh", "-c", "exit 1"])
    process_handler = SubprocessProcessHandler(process)
    self.assertEquals(process_handler.wait(), 1)

  def test_exit_0(self):
    process = subprocess.Popen(["/bin/sh", "-c", "exit 0"])
    process_handler = SubprocessProcessHandler(process)
    self.assertEquals(process_handler.wait(), 0)
