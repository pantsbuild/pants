# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import signal
import time
from contextlib import contextmanager
from textwrap import dedent

from pants.base.build_environment import get_buildroot
from pants.base.exception_sink import ExceptionSink
from pants.util.contextutil import environment_as, temporary_dir
from pants.util.dirutil import read_file, safe_file_dump, safe_mkdir, touch
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class ExceptionSinkIntegrationTest(PantsRunIntegrationTest):

  def _lifecycle_stub_cmdline(self):
    # Load the testprojects pants-plugins to get some testing tasks and subsystems.
    testproject_backend_src_dir = os.path.join(
      get_buildroot(), 'testprojects/pants-plugins/src/python')
    testproject_backend_pkg_name = 'test_pants_plugin'
    lifecycle_stub_cmdline = [
      '--no-enable-pantsd',
      "--pythonpath=+['{}']".format(testproject_backend_src_dir),
      "--backend-packages=+['{}']".format(testproject_backend_pkg_name),
      # This task will always raise an exception.
      'lifecycle-stub-goal',
    ]

    return lifecycle_stub_cmdline

  def test_reset_exiter(self):
    """Test that when reset_exiter() is used that sys.excepthook uses the new Exiter."""
    lifecycle_stub_cmdline = self._lifecycle_stub_cmdline()

    # The normal Exiter will print the exception message on an unhandled exception.
    normal_exiter_run = self.run_pants(lifecycle_stub_cmdline)
    self.assert_failure(normal_exiter_run)
    self.assertIn('erroneous!', normal_exiter_run.stderr_data)
    self.assertNotIn('NEW MESSAGE', normal_exiter_run.stderr_data)

    # The exiter that gets added when this option is changed prints that option to stderr.
    changed_exiter_run = self.run_pants([
                                          "--lifecycle-stubs-add-exiter-message='{}'".format('NEW MESSAGE'),
                                        ] + lifecycle_stub_cmdline)
    self.assert_failure(changed_exiter_run)
    self.assertIn('erroneous!', changed_exiter_run.stderr_data)
    self.assertIn('NEW MESSAGE', changed_exiter_run.stderr_data)
