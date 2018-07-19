# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.backend.python.tasks.isort_run import IsortRun
from pants_test.pants_run_integration_test import PantsRunIntegrationTest, ensure_daemon


class IsortRunIntegrationTest(PantsRunIntegrationTest):

  @ensure_daemon
  def test_isort_no_python_sources_should_noop(self):
    command = ['-ldebug',
               'fmt.isort',
               'testprojects/tests/java/org/pantsbuild/testproject/dummies/::',
               '--',
               '--check-only']
    pants_run = self.run_pants(command=command)
    self.assert_success(pants_run)
    self.assertIn(IsortRun.NOOP_MSG_HAS_TARGET_BUT_NO_SOURCE, pants_run.stderr_data)
