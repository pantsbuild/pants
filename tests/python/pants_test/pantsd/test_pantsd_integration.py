# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.pantsd.process_manager import ProcessManager
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


# TODO: ProcessManager's `.pids` needs to be made relocatable for fully concurrent-safe tests.
# For testing purposes, it should be safe to locate `.pids` inside the workdir.
class PantsDaemonMonitor(ProcessManager):
  def __init__(self):
    super(PantsDaemonMonitor, self).__init__(name='pantsd')

  def await_pantsd(self, timeout=10):
    self._pid = self.await_pid(timeout)
    self.assert_running()

  def assert_running(self):
    assert self._pid is not None and self.is_alive(), 'pantsd should be running!'

  def assert_stopped(self):
    assert self._pid is not None and self.is_dead(), 'pantsd should be stopped!'


def print_pantsd_log(workdir):
  # Surface the pantsd log for easy viewing via pytest's `-s` (don't redirect stdio) option.
  print('pantsd.log:\n')
  with open('{}/pantsd/pantsd.log'.format(workdir)) as f:
    for line in f:
      print(line, end='')


class TestPantsDaemonIntegration(PantsRunIntegrationTest):
  def test_pantsd_run(self):
    pantsd_config = {'GLOBAL': {'enable_pantsd': True, 'level': 'debug'}}
    checker = PantsDaemonMonitor()

    with self.temporary_workdir() as workdir:
      # Explicitly kill any running pantsd instances for the current buildroot.
      self.assert_success(
        self.run_pants_with_workdir(['kill-pantsd'], workdir)
      )

      # Start pantsd implicitly via a throwaway invocation.
      self.assert_success(
        self.run_pants_with_workdir(['help'], workdir, pantsd_config)
      )
      checker.await_pantsd()

      # This run should execute via pantsd testing the end to end client/server.
      self.assert_success(
        self.run_pants_with_workdir(['help-advanced'], workdir, pantsd_config)
      )
      checker.assert_running()

      # This tests a deeper pantsd-based run by actually invoking a full compile.
      self.assert_success(
        self.run_pants_with_workdir(
          ['compile', 'examples/src/scala/org/pantsbuild/example/hello/welcome'],
          workdir,
          pantsd_config)
      )
      checker.assert_running()

      # Explicitly kill pantsd (from a pantsd-launched runner).
      self.assert_success(
        self.run_pants_with_workdir(['kill-pantsd'], workdir, pantsd_config)
      )
      checker.assert_stopped()

      print_pantsd_log(workdir)

  def test_pantsd_run_with_watchman(self):
    pantsd_config = {'GLOBAL': {'enable_pantsd': True,
                                'level': 'debug'},
                     'pantsd': {'fs_event_detection': True},
                     # The absolute paths in CI can often exceed the UNIX socket path limitation
                     # (104-108+ characters), so we override that here with a shorter path.
                     'watchman': {'socket_path': '/tmp/watchman.{}.sock'.format(os.getpid())}}
    checker = PantsDaemonMonitor()

    with self.temporary_workdir() as workdir:
      # Explicitly kill any running pantsd instances for the current buildroot.
      self.assert_success(
        self.run_pants_with_workdir(['kill-pantsd'], workdir)
      )

      # Start pantsd implicitly via a throwaway invocation.
      self.assert_success(
        self.run_pants_with_workdir(['help'], workdir, pantsd_config)
      )
      checker.await_pantsd()

      # This run should execute via pantsd testing the end to end client/server.
      self.assert_success(
        self.run_pants_with_workdir(['list', '3rdparty/python::'], workdir, pantsd_config)
      )
      checker.assert_running()

      # And again using the cached BuildGraph.
      self.assert_success(
        self.run_pants_with_workdir(['list', '3rdparty/python::'], workdir, pantsd_config)
      )
      checker.assert_running()

      # Explicitly kill pantsd (from a pantsd-launched runner).
      self.assert_success(
        self.run_pants_with_workdir(['kill-pantsd'], workdir, pantsd_config)
      )
      checker.assert_stopped()

      print_pantsd_log(workdir)
