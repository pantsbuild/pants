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

  def test_interpreter_constraints_parsing(self):
    python_setup = global_subsystem_instance(PythonSetup)
    target_adaptors = [
      # NB: This target will use the global --python-setup-interpreter-constraints.
      PythonTargetAdaptor(compatibility=None),
      PythonTargetAdaptor(compatibility=["CPython>=400"]),
    ]
    self.assertEqual(
      parse_interpreter_constraints(python_setup, target_adaptors),
      [
        "--interpreter-constraint", "CPython>=2.7,<3",
        "--interpreter-constraint", "CPython>=3.6,<4",
        "--interpreter-constraint", "CPython>=400"
      ]
    )
