# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import sys


class Console(object):

  @property
  def stdout(self):
    return sys.stdout

  @property
  def stderr(self):
    return sys.stderr

  def write_stdout(self, payload):
    self.stdout.write(payload)

  def write_stderr(self, payload):
    self.stderr.write(payload)

  def print_stdout(self, payload):
    print(payload, file=self.stdout)

  def print_stderr(self, payload):
    print(payload, file=self.stderr)
