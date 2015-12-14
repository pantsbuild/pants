# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import mock

from pants.pantsd.pants_daemon import PantsDaemon
from pants.pantsd.subsystem.pants_daemon_launcher import PantsDaemonLauncher
from pants_test.base_test import BaseTest
from pants_test.subsystem.subsystem_util import create_subsystem


class PantsDaemonLauncherTest(BaseTest):
  PDL_PATCH_OPTS = dict(autospec=True, spec_set=True, return_value=(None, None))

  def setUp(self):
    super(PantsDaemonLauncherTest, self).setUp()
    self.launcher = create_subsystem(PantsDaemonLauncher,
                                     pants_workdir='/pants_workdir',
                                     level='info')
    self.mock_pantsd = mock.create_autospec(PantsDaemon, spec_set=True)
    self.launcher._pantsd = self.mock_pantsd

  @mock.patch.object(PantsDaemonLauncher, '_setup_services', **PDL_PATCH_OPTS)
  def test_maybe_launch(self, mock_setup_services):
    self.mock_pantsd.is_alive.return_value = False

    self.launcher.maybe_launch()

    self.assertGreater(mock_setup_services.call_count, 0)
    self.assertGreater(self.mock_pantsd.is_alive.call_count, 0)
    self.assertGreater(self.mock_pantsd.daemonize.call_count, 0)

  @mock.patch.object(PantsDaemonLauncher, '_setup_services', **PDL_PATCH_OPTS)
  def test_maybe_launch_already_alive(self, mock_setup_services):
    self.mock_pantsd.is_alive.return_value = True

    self.launcher.maybe_launch()

    self.assertEqual(mock_setup_services.call_count, 0)
    self.assertGreater(self.mock_pantsd.is_alive.call_count, 0)
    self.assertEqual(self.mock_pantsd.daemonize.call_count, 0)
