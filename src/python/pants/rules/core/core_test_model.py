# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from future.utils import text_type

from pants.util.objects import datatype, enum


class Status(enum(['SUCCESS', 'FAILURE'])): pass


class TestResult(datatype([
  ('status', Status),
  # The stdout of the test runner (which may or may not include actual testcase output).
  ('stdout', text_type),
  ('stderr', text_type),
])):

  # Prevent this class from being detected by pytest as a test class.
  __test__ = False
