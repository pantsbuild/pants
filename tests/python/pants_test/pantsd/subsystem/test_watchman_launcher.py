# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import mock

from pants.pantsd.subsystem.watchman_launcher import WatchmanLauncher
from pants.pantsd.watchman import Watchman
from pants_test.base_test import BaseTest
from pants_test.subsystem.subsystem_util import create_subsystem


class TestWatchmanLauncher(BaseTest):
  def setUp(self):
    BaseTest.setUp(self)
    self.watchman_launcher = create_subsystem(WatchmanLauncher,
                                              pants_workdir='/pants_workdir',
                                              level='info')

  def test_options_defaults(self):
    self.assertIsNone(self.watchman_launcher._watchman_path)
    self.assertEquals(self.watchman_launcher._watchman_log_level, '1')

  def create_mock_watchman(self, is_alive):
    mock_watchman = mock.create_autospec(Watchman, spec_set=False)
    mock_watchman.watchman_path = None
    mock_watchman.ExecutionError = Watchman.ExecutionError
    mock_watchman.is_alive.return_value = is_alive
    return mock_watchman

  def test_maybe_launch(self):
    mock_watchman = self.create_mock_watchman(False)

    self.watchman_launcher._watchman = mock_watchman
    self.assertTrue(self.watchman_launcher.maybe_launch())

    mock_watchman.is_alive.assert_called_once_with()
    mock_watchman.launch.assert_called_once_with()

  def test_maybe_launch_already_alive(self):
    mock_watchman = self.create_mock_watchman(True)

    self.watchman_launcher._watchman = mock_watchman
    self.assertTrue(self.watchman_launcher.maybe_launch())

    mock_watchman.is_alive.assert_called_once_with()
    assert not mock_watchman.launch.called

  def test_maybe_launch_error(self):
    mock_watchman = self.create_mock_watchman(False)
    mock_watchman.launch.side_effect = Watchman.ExecutionError('oops!')

    self.watchman_launcher._watchman = mock_watchman
    self.assertFalse(self.watchman_launcher.maybe_launch())

    mock_watchman.is_alive.assert_called_once_with()
    mock_watchman.launch.assert_called_once_with()

  def test_watchman_property(self):
    with mock.patch.object(Watchman, '_resolve_watchman_path'):
      self.assertIsInstance(self.watchman_launcher.watchman, Watchman)
