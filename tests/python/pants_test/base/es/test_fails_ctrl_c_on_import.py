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

  def _get_log_file_paths(self, workdir, pants_run):
    pid_specific_log_file = ExceptionSink.exceptions_log_path(for_pid=pants_run.pid, in_dir=workdir)
    self.assertTrue(os.path.isfile(pid_specific_log_file))

    shared_log_file = ExceptionSink.exceptions_log_path(in_dir=workdir)
    self.assertTrue(os.path.isfile(shared_log_file))

    self.assertNotEqual(pid_specific_log_file, shared_log_file)

    return (pid_specific_log_file, shared_log_file)

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

  def test_fails_ctrl_c_on_import(self):
    with temporary_dir() as tmpdir:
      with environment_as(_RAISE_KEYBOARDINTERRUPT_ON_IMPORT='True'):
        # TODO: figure out the cwd of the pants subprocess, not just the "workdir"!
        pants_run = self.run_pants_with_workdir(self._lifecycle_stub_cmdline(), workdir=tmpdir)
        self.assert_failure(pants_run)

        self.assertIn(dedent("""\
        Interrupted by user:
        ctrl-c during import!
        """), pants_run.stderr_data)

        pid_specific_log_file, shared_log_file = self._get_log_file_paths(tmpdir, pants_run)

        self.assertEqual('', read_file(pid_specific_log_file))
        self.assertEqual('', read_file(shared_log_file))
