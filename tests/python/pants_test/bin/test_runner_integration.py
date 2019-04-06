# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os

from pants.base.build_environment import get_buildroot
from pants.option.scope import GLOBAL_SCOPE_CONFIG_SECTION
from pants_test.pants_run_integration_test import PantsRunIntegrationTest
from pants_test.testutils.py2_compat import assertRegex


class RunnerIntegrationTest(PantsRunIntegrationTest):
  """Test logic performed in PantsRunner."""

  def _deprecation_warning_cmdline(self):
    # Load the testprojects pants-plugins to get some testing tasks and subsystems.
    testproject_backend_src_dir = os.path.join(
      get_buildroot(), 'testprojects/pants-plugins/src/python')
    testproject_backend_pkg_name = 'test_pants_plugin'
    deprecation_warning_cmdline = [
      '--no-enable-pantsd',
      "--pythonpath=+['{}']".format(testproject_backend_src_dir),
      "--backend-packages=+['{}']".format(testproject_backend_pkg_name),
      # This task will always emit a DeprecationWarning.
      'deprecation-warning-task',
    ]
    return deprecation_warning_cmdline

  def test_warning_filter(self):
    cmdline = self._deprecation_warning_cmdline()

    warning_run = self.run_pants(cmdline)
    self.assert_success(warning_run)
    assertRegex(
      self,
      warning_run.stderr_data,
      '^WARN\\].*DeprecationWarning: DEPRECATED: This is a test warning!')

    non_warning_run = self.run_pants(cmdline, config={
      GLOBAL_SCOPE_CONFIG_SECTION: {
        # NB: We do *not* include the exclamation point at the end, which tests that the regexps
        # match from the beginning of the warning string, and don't require matching the entire
        # string! We also lowercase the message to check that they are matched case-insensitively.
        'ignore_pants_warnings': ['deprecated: this is a test warning']
      },
    })
    self.assert_success(non_warning_run)
    self.assertNotIn('DEPRECATED', non_warning_run.stderr_data)
    self.assertNotIn('test warning', non_warning_run.stderr_data)
