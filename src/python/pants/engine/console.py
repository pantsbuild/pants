# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import sys


class Console(object):
  def __init__(self, stdout=None, stderr=None):
    self._stdout = stdout or sys.stdout
    self._stderr = stderr or sys.stderr

  @property
  def stdout(self):
    return self._stdout

  @property
  def stderr(self):
    return self._stderr

  def write_stdout(self, payload):
    self.stdout.write(payload)

  def write_stderr(self, payload):
    self.stderr.write(payload)

  def print_stdout(self, payload):
    print(payload, file=self.stdout)

  def print_stderr(self, payload):
    print(payload, file=self.stderr)

  def flush(self):
    self.stdout.flush()
    self.stderr.flush()
