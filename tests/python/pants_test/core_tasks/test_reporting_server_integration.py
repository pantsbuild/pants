# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import re

import psutil

from pants_test.pants_run_integration_test import PantsRunIntegrationTest
from pants_test.testutils.py2_compat import assertRegex


class ReportingServerIntegration(PantsRunIntegrationTest):

  def test_reporting_server_lifecycle(self):
    start_server_run = self.run_pants(['server'])
    self.assert_success(start_server_run)
    assertRegex(self, start_server_run.stderr_data, 'Launched server with pid ([0-9]+) at http://localhost:([0-9]+)')
    server_pid_port_match = re.search(
      'Launched server with pid ([0-9]+) at http://localhost:([0-9]+)',
      start_server_run.stderr_data)
    pid = int(server_pid_port_match.group(1))
    self.assertTrue(psutil.pid_exists(pid))
    port = int(server_pid_port_match.group(2))

    kill_server_run = self.run_pants(['killserver'])
    self.assert_success(kill_server_run)
    self.assertIn('Killing server with pid {} at http://localhost:{}'.format(pid, port),
                  kill_server_run.stderr_data)
    assertRegex(self, kill_server_run.stderr_data, """\
timestamp: [^\n]+
Signal 15 \\(SIGTERM\\) was raised\\. Exiting with failure\\.
""")
    self.assertFalse(psutil.pid_exists(pid))
