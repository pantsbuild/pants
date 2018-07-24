# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import sys
import unittest
from contextlib import contextmanager

from pants.util.contextutil import stdio_as, temporary_file


class ContextutilTestBase(unittest.TestCase):

  @contextmanager
  def stdio_as_tempfiles(self, stdin_data, stdout_data, stderr_data, strict_text_match=True):
    """Harness to replace `sys.std*` with tempfiles.

    Validates that all files are read/written/flushed correctly, and acts as a
    contextmanager to allow for recursive tests.
    """

    with temporary_file() as tmp_stdin,\
         temporary_file() as tmp_stdout,\
         temporary_file() as tmp_stderr:
      print(stdin_data, file=tmp_stdin)
      tmp_stdin.seek(0)
      # Read prepared content from stdin, and write content to stdout/stderr.
      with stdio_as(stdout_fd=tmp_stdout.fileno(),
                    stderr_fd=tmp_stderr.fileno(),
                    stdin_fd=tmp_stdin.fileno()):
        self.assertEquals(sys.stdin.fileno(), 0)
        self.assertEquals(sys.stdout.fileno(), 1)
        self.assertEquals(sys.stderr.fileno(), 2)

        self.assertEquals(stdin_data, sys.stdin.read().strip())
        yield

      tmp_stdout.seek(0)
      tmp_stderr.seek(0)
      if strict_text_match:
        self.assertEquals(stdout_data, tmp_stdout.read().strip())
        self.assertEquals(stderr_data, tmp_stderr.read().strip())
      else:
        self.assertIn(stdout_data, tmp_stdout.read().strip())
        self.assertIn(stderr_data, tmp_stderr.read().strip())
