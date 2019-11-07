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

  def test_reset_interactive_output_stream(self):
    """Test redirecting the terminal output stream to a separate file."""
    lifecycle_stub_cmdline = self._lifecycle_stub_cmdline()

    failing_pants_run = self.run_pants(lifecycle_stub_cmdline)
    self.assert_failure(failing_pants_run)
    self.assertIn('erroneous!', failing_pants_run.stderr_data)

    with temporary_dir() as tmpdir:
      some_file = os.path.join(tmpdir, 'some_file')
      safe_file_dump(some_file, '')
      redirected_pants_run = self.run_pants([
                                              "--lifecycle-stubs-new-interactive-stream-output-file={}".format(some_file),
                                            ] + lifecycle_stub_cmdline)
      self.assert_failure(redirected_pants_run)
      # The Exiter prints the final error message to whatever the interactive output stream is set
      # to, so when it's redirected it won't be in stderr.
      self.assertNotIn('erroneous!', redirected_pants_run.stderr_data)
      self.assertIn('erroneous!', read_file(some_file))
