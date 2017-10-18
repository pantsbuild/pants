# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import mock

from pants.pantsd.pants_daemon import PantsDaemon
from pants.pantsd.pants_daemon_launcher import PantsDaemonLauncher
from pants.pantsd.watchman_launcher import WatchmanLauncher
from pants_test.base_test import BaseTest


class PantsDaemonLauncherTest(BaseTest):
  PDL_PATCH_OPTS = dict(autospec=True, spec_set=True, return_value=(None, None, None))

  def pants_daemon_launcher(self, cli_options=()):
    bootstrap_options = self.get_bootstrap_options(cli_options)
    pdl = PantsDaemonLauncher(bootstrap_options)
    pdl.pantsd = self.mock_pantsd
    pdl.watchman_launcher = self.mock_watchman_launcher
    return pdl

  def setUp(self):
    super(PantsDaemonLauncherTest, self).setUp()
    self.mock_pantsd = mock.create_autospec(PantsDaemon, spec_set=True)
    self.mock_watchman_launcher = mock.create_autospec(WatchmanLauncher, spec_set=True)

  @mock.patch.object(PantsDaemonLauncher, '_setup_services', **PDL_PATCH_OPTS)
  def test_maybe_launch(self, mock_setup_services):
    self.mock_pantsd.is_alive.return_value = False

    pdl = self.pants_daemon_launcher()
    pdl.maybe_launch()

    self.assertGreater(mock_setup_services.call_count, 0)
    self.assertGreater(self.mock_pantsd.is_alive.call_count, 0)
    self.assertGreater(self.mock_pantsd.daemonize.call_count, 0)

  @mock.patch.object(PantsDaemonLauncher, '_setup_services', **PDL_PATCH_OPTS)
  def test_maybe_launch_already_alive(self, mock_setup_services):
    self.mock_pantsd.is_alive.return_value = True

    pdl = self.pants_daemon_launcher(['--pantsd-enabled'])
    pdl.maybe_launch()

    self.assertEqual(mock_setup_services.call_count, 0)
    self.assertGreater(self.mock_pantsd.is_alive.call_count, 0)
    self.assertEqual(self.mock_pantsd.daemonize.call_count, 0)
