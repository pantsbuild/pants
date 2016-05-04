# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from contextlib import contextmanager

import mock

from pants.pantsd.pants_daemon import PantsDaemon
from pants.pantsd.subsystem.pants_daemon_launcher import PantsDaemonLauncher
from pants.pantsd.subsystem.watchman_launcher import WatchmanLauncher
from pants_test.base_test import BaseTest
from pants_test.subsystem.subsystem_util import subsystem_instance


class PantsDaemonLauncherTest(BaseTest):
  PDL_PATCH_OPTS = dict(autospec=True, spec_set=True, return_value=(None, None))

  @contextmanager
  def pants_daemon_launcher(self, options=None):
    options = options or {}
    with subsystem_instance(PantsDaemonLauncher.Factory, **options) as factory:
      pdl = factory.create(None)
      pdl.pantsd = self.mock_pantsd
      pdl.watchman_launcher = self.mock_watchman_launcher
      yield pdl

  def setUp(self):
    super(PantsDaemonLauncherTest, self).setUp()
    self.mock_pantsd = mock.create_autospec(PantsDaemon, spec_set=True)
    self.mock_watchman_launcher = mock.create_autospec(WatchmanLauncher, spec_set=True)

  @mock.patch.object(PantsDaemonLauncher, '_setup_services', **PDL_PATCH_OPTS)
  def test_maybe_launch(self, mock_setup_services):
    self.mock_pantsd.is_alive.return_value = False

    with self.pants_daemon_launcher() as pdl:
      pdl.maybe_launch()

    self.assertGreater(mock_setup_services.call_count, 0)
    self.assertGreater(self.mock_pantsd.is_alive.call_count, 0)
    self.assertGreater(self.mock_pantsd.daemonize.call_count, 0)

  @mock.patch.object(PantsDaemonLauncher, '_setup_services', **PDL_PATCH_OPTS)
  def test_maybe_launch_already_alive(self, mock_setup_services):
    self.mock_pantsd.is_alive.return_value = True
    options = {'default': {'pantsd_enabled': 'true'}}

    with self.pants_daemon_launcher(options) as pdl:
      pdl.maybe_launch()

    self.assertEqual(mock_setup_services.call_count, 0)
    self.assertGreater(self.mock_pantsd.is_alive.call_count, 0)
    self.assertEqual(self.mock_pantsd.daemonize.call_count, 0)
