# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

from pants.util.process_handler import SubprocessProcessHandler, subprocess


class TestSubprocessProcessHandler(unittest.TestCase):
  def test_exit_1(self):
    process = subprocess.Popen(["/bin/sh", "-c", "exit 1"])
    process_handler = SubprocessProcessHandler(process)
    self.assertEquals(process_handler.wait(), 1)

  def test_exit_0(self):
    process = subprocess.Popen(["/bin/sh", "-c", "exit 0"])
    process_handler = SubprocessProcessHandler(process)
    self.assertEquals(process_handler.wait(), 0)

  def test_communicate_teeing_retrieves_stdout_and_stderr(self):
    process = subprocess.Popen(["/bin/bash", "-c",
"""
  echo "1out"
  echo >&2 "1err"
  sleep 0.05
  echo >&2 "2err"
  echo "2out"
  sleep 0.05
  echo "3out"
  sleep 0.05
  echo >&2 "3err"
  sleep 0.05
exit 1
"""], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    process_handler = SubprocessProcessHandler(process)
    self.assertEquals(process_handler.communicate_teeing_stdout_and_stderr(), (
"""1out
2out
3out
""", """1err
2err
3err
"""))
    # Sadly, this test doesn't test that sys.std{out,err} also receive the output.
    # You can see it when you run it, but any way we have of spying on sys.std{out,err}
    # isn't picklable enough to write a test which works.
