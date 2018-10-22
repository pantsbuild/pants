# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from builtins import str

from pants.util.objects import datatype


class Status(object):
  SUCCESS = str('SUCCESS')
  FAILURE = str('FAILURE')


class TestResult(datatype([
  # One of the Status pseudo-enum values capturing whether the run was successful.
  ('status', str),
  # The stdout of the test runner (which may or may not include actual testcase output).
  ('stdout', str)
])):
  # Prevent this class from being detected by pytest as a test class.
  __test__ = False
