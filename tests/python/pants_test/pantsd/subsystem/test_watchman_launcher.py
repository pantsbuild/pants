# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import mock

from pants.pantsd.subsystem.watchman_launcher import WatchmanLauncher
from pants.pantsd.watchman import Watchman
from pants_test.base_test import BaseTest
from pants_test.subsystem.subsystem_util import global_subsystem_instance


class TestWatchmanLauncher(BaseTest):
  def watchman_launcher(self, options=None):
    options = options or {}
    return global_subsystem_instance(WatchmanLauncher.Factory, options=options).create()

  def create_mock_watchman(self, is_alive):
    mock_watchman = mock.create_autospec(Watchman, spec_set=False)
    mock_watchman.ExecutionError = Watchman.ExecutionError
    mock_watchman.is_alive.return_value = is_alive
    return mock_watchman

  def test_maybe_launch(self):
    mock_watchman = self.create_mock_watchman(False)

    wl = self.watchman_launcher()
    wl.watchman = mock_watchman
    self.assertTrue(wl.maybe_launch())

    mock_watchman.is_alive.assert_called_once_with()
    mock_watchman.launch.assert_called_once_with()

  def test_maybe_launch_already_alive(self):
    mock_watchman = self.create_mock_watchman(True)

    wl = self.watchman_launcher()
    wl.watchman = mock_watchman
    self.assertTrue(wl.maybe_launch())

    mock_watchman.is_alive.assert_called_once_with()
    self.assertFalse(mock_watchman.launch.called)

  def test_maybe_launch_error(self):
    mock_watchman = self.create_mock_watchman(False)
    mock_watchman.launch.side_effect = Watchman.ExecutionError('oops!')

    wl = self.watchman_launcher()
    wl.watchman = mock_watchman
    with self.assertRaises(wl.watchman.ExecutionError):
      wl.maybe_launch()

    mock_watchman.is_alive.assert_called_once_with()
    mock_watchman.launch.assert_called_once_with()

  def test_watchman_property(self):
    wl = self.watchman_launcher()
    self.assertIsInstance(wl.watchman, Watchman)

  def test_watchman_socket_path(self):
    expected_path = '/a/shorter/path'
    options = {WatchmanLauncher.Factory.options_scope: {'socket_path': expected_path}}
    wl = self.watchman_launcher(options)
    self.assertEquals(wl.watchman._sock_file, expected_path)
