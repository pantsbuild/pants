# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.python.tasks.python_isort import IsortPythonTask
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class PythonIsortTest(PantsRunIntegrationTest):

  def test_isort_passthru_has_target_but_not_python(self):
    command = ['fmt.isort',
               'testprojects/tests/java/org/pantsbuild/testproject/dummies/::',
               '--',
               '--check-only']
    pants_run = self.run_pants(command=command)
    self.assert_success(pants_run)
    self.assertIn(IsortPythonTask.NOOP_MSG_HAS_TARGET_BUT_NO_SOURCE, pants_run.stdout_data)
