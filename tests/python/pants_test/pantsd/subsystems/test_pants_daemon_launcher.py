# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging

import mock

from pants.pantsd.pants_daemon import PantsDaemon
from pants.pantsd.subsystems.pants_daemon_launcher import PantsDaemonLauncher
from pants_test.base_test import BaseTest
from pants_test.subsystem.subsystem_util import create_subsystem


class TestPantsDaemonLauncher(BaseTest):
  def setUp(self):
    BaseTest.setUp(self)
    self.launcher = create_subsystem(PantsDaemonLauncher)

  def test_options_defaults(self):
    self.assertFalse(self.launcher.options.enabled)
    self.assertEquals(self.launcher.options.http_host, '127.0.0.1')
    self.assertIsNone(self.launcher.options.http_port)
    self.assertIsNone(self.launcher.options.log_dir)
    self.assertIsNone(self.launcher.options.log_level)

  def create_mock_launcher(self, is_alive):
    mock_pantsd = mock.create_autospec(PantsDaemon, spec_set=True)
    mock_pantsd.is_alive.return_value = is_alive
    return mock_pantsd

  def test_maybe_launch(self):
    mock_pantsd = self.create_mock_launcher(False)

    self.launcher.options.enabled = True
    self.launcher.pantsd = mock_pantsd
    self.launcher.maybe_launch()

    mock_pantsd.is_alive.assert_called_once_with()
    mock_pantsd.daemonize.assert_called_once_with(post_fork_child_opts=dict(
      log_level=logging.getLogger().getEffectiveLevel()
    ))

  def test_maybe_launch_disabled(self):
    mock_pantsd = self.create_mock_launcher(False)

    self.launcher.options.enabled = False
    self.launcher.pantsd = mock_pantsd
    self.launcher.maybe_launch()

    assert not mock_pantsd.is_alive.called
    assert not mock_pantsd.daemonize.called

  def test_maybe_launch_already_alive(self):
    mock_pantsd = self.create_mock_launcher(True)

    self.launcher.options.enabled = True
    self.launcher.pantsd = mock_pantsd
    self.launcher.maybe_launch()

    mock_pantsd.is_alive.assert_called_once_with()
    assert not mock_pantsd.daemonize.called
