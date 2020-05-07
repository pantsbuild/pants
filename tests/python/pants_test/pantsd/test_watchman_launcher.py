# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import unittest.mock

from pants.pantsd.watchman import Watchman
from pants.pantsd.watchman_launcher import WatchmanLauncher
from pants.testutil.test_base import TestBase


class TestWatchmanLauncher(TestBase):
    def watchman_launcher(self, cli_options=()):
        options = ("--watchman-enable", *cli_options)
        bootstrap_options = self.get_bootstrap_options(options)
        return WatchmanLauncher.create(bootstrap_options)

    def create_mock_watchman(self, is_alive):
        mock_watchman = unittest.mock.create_autospec(Watchman, spec_set=False)
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
        mock_watchman.launch.side_effect = Watchman.ExecutionError("oops!")

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
        expected_path = "/a/shorter/path"
        options = [f"--watchman-socket-path={expected_path}"]
        wl = self.watchman_launcher(options)
        self.assertEqual(wl.watchman._sock_file, expected_path)
