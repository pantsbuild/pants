# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from unittest import TestCase

from pants.backend.python.rules.python_test_runner import parse_interpreter_constraints


class TestPythonTestRunner(TestCase):

  def test_interpreter_constraints_none_used(self):
    # Want
    # * python_setup to have no interpreter constraints
    # * hydrated_target to have no `compatibility`
    self.assertEqual(
      parse_interpreter_constraints(),
      []
    )

  def test_interpreter_constraints_global_used(self):
    # Want
    # * python_setup to have constraints ["CPython>=400"]
    # * hydrated_target to have no `compatibility`
    self.assertEqual(
      parse_interpreter_constraints(),
      ["--interpreter-constraint", "CPython>=400"]
    )

  def test_interpreter_constraints_compability_field_used(self):
    # Want
    # * python_setup to have no interpreter constraints
    # * hydrated_target to have `compatibility` ["CPython>=400"]
    self.assertEqual(
      parse_interpreter_constraints(),
      ["--interpreter-constraint", "CPython>=400"]
    )

  def test_interpreter_constraints_multiple_constraints(self):
    # Want
    # * python_setup to have no interpreter constraints
    # * hydrated_targets to have `compatibility` ["CPython>=400", "CPython<=1"]
    self.assertEqual(
      parse_interpreter_constraints(),
      ["--interpreter-constraint", "CPython<=1", "--interpreter-constraint", "CPython>=400"]
    )
