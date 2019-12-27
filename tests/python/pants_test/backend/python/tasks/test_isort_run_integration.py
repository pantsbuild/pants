# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.tasks.isort_run import IsortRun
from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest, ensure_daemon


class IsortRunIntegrationTest(PantsRunIntegrationTest):

  @ensure_daemon
  def test_isort_no_python_sources_should_noop(self):
    command = [
      '-ldebug',
      'fmt.isort',
      'testprojects/tests/java/org/pantsbuild/testproject/dummies/::',
      "--isort-args='--check-only'",
    ]
    pants_run = self.run_pants(command=command)
    self.assert_success(pants_run)
    assert IsortRun.NOOP_MSG_HAS_TARGET_BUT_NO_SOURCE in pants_run.stderr_data
