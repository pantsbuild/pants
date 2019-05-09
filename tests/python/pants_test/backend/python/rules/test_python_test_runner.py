# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from unittest import TestCase

from pants.backend.python.rules.python_test_runner import parse_interpreter_constraints
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.engine.legacy.structs import PythonTargetAdaptor
from pants_test.subsystem.subsystem_util import global_subsystem_instance


class TestPythonTestRunner(TestCase):

  def assert_interpreter_constraints_parsed(
    self, python_setup_constraints, target_constraints, expected
  ):
    python_setup = (
      global_subsystem_instance(PythonSetup)
      if python_setup_constraints is None else
      global_subsystem_instance(
        PythonSetup,
        options={PythonSetup.options_scope: {"interpreter_constraints": python_setup_constraints}}
      )
    )
    target_adaptor = PythonTargetAdaptor(compatibility=target_constraints)
    self.assertEqual(parse_interpreter_constraints(python_setup, [target_adaptor]), expected)

  # TODO: fails because it's picking up global values
  def test_interpreter_constraints_none_used(self):
    self.assert_interpreter_constraints_parsed(
      python_setup_constraints=None,
      target_constraints=None,
      expected=[]
    )

  # TODO: fails because its using the global defaults, rather than what we try to specify.
  def test_interpreter_constraints_global_used(self):
    self.assert_interpreter_constraints_parsed(
      python_setup_constraints=["CPython>=400"],
      target_constraints=None,
      expected=["--interpreter-constraint", "CPython>=400"]
    )

  def test_interpreter_constraints_compability_field_used(self):
    self.assert_interpreter_constraints_parsed(
      python_setup_constraints=None,
      target_constraints=["CPython<=1", "CPython>=400",],
      expected=[
        "--interpreter-constraint", "CPython<=1", "--interpreter-constraint", "CPython>=400"
      ]
    )
