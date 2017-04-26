# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import time
from contextlib import contextmanager

from pants.pantsd.process_manager import ProcessManager
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class PantsDaemonMonitor(ProcessManager):
  def __init__(self, metadata_base_dir=None):
    super(PantsDaemonMonitor, self).__init__(name='pantsd', metadata_base_dir=metadata_base_dir)

  def await_pantsd(self, timeout=10):
    self._pid = self.await_pid(timeout)
    self.assert_running()

  def assert_running(self, sleep=0):
    time.sleep(sleep)
    assert self._pid is not None and self.is_alive(), 'pantsd should be running!'

  def assert_stopped(self, sleep=0):
    time.sleep(sleep)
    assert self._pid is not None and self.is_dead(), 'pantsd should be stopped!'


def read_pantsd_log(workdir):
  # Surface the pantsd log for easy viewing via pytest's `-s` (don't capture stdio) option.
  with open('{}/pantsd/pantsd.log'.format(workdir)) as f:
    for line in f:
      yield line.strip()


class TestPantsDaemonIntegration(PantsRunIntegrationTest):
  @contextmanager
  def pantsd_test_context(self, config=None):
    with self.temporary_workdir() as workdir_base:
      pid_dir = os.path.join(workdir_base, '.pids')
      workdir = os.path.join(workdir_base, '.workdir.pants.d')
      pantsd_config = config or {}
      pantsd_config.setdefault('GLOBAL', {'enable_pantsd': True,
                                          'level': 'debug',
                                          'pants_subprocessdir': pid_dir})
      checker = PantsDaemonMonitor(pid_dir)
      yield workdir, pantsd_config, checker

  def test_pantsd_run(self):
    with self.pantsd_test_context() as (workdir, pantsd_config, checker):
      # Explicitly kill any running pantsd instances for the current buildroot.
      self.assert_success(self.run_pants_with_workdir(['kill-pantsd'], workdir, pantsd_config))
      try:
        # Start pantsd implicitly via a throwaway invocation.
        self.assert_success(self.run_pants_with_workdir(['help'], workdir, pantsd_config))
        checker.await_pantsd()

        # This run should execute via pantsd testing the end to end client/server.
        self.assert_success(self.run_pants_with_workdir(['help-advanced'], workdir, pantsd_config))
        checker.assert_running()

        # This tests a deeper pantsd-based run by actually invoking a full compile.
        self.assert_success(
          self.run_pants_with_workdir(
            ['compile', 'examples/src/scala/org/pantsbuild/example/hello/welcome'],
            workdir,
            pantsd_config)
        )
        checker.assert_running()
      finally:
        # Explicitly kill pantsd (from a pantsd-launched runner).
        self.assert_success(self.run_pants_with_workdir(['kill-pantsd'], workdir, pantsd_config))

      checker.assert_stopped()

      for line in read_pantsd_log(workdir):
        print(line)

  def test_pantsd_run_with_watchman(self):
    # The absolute paths in CI can exceed the UNIX socket path limitation
    # (>104-108 characters), so we override that here with a shorter path.
    config = {'watchman': {'socket_path': '/tmp/watchman.{}.sock'.format(os.getpid())}}

    with self.pantsd_test_context(config) as (workdir, pantsd_config, checker):
      print('log: {}/pantsd/pantsd.log'.format(workdir))
      # Explicitly kill any running pantsd instances for the current buildroot.
      print('\nkill-pantsd')
      self.assert_success(self.run_pants_with_workdir(['kill-pantsd'], workdir, pantsd_config))
      try:
        # Start pantsd implicitly via a throwaway invocation.
        print('help')
        self.assert_success(self.run_pants_with_workdir(['help'], workdir, pantsd_config))
        checker.await_pantsd()

        # This run should execute via pantsd testing the end to end client/server.
        print('list')
        self.assert_success(self.run_pants_with_workdir(['list', '3rdparty:'],
                                                        workdir,
                                                        pantsd_config))
        checker.assert_running(3)

        print('list')
        self.assert_success(self.run_pants_with_workdir(['list', ':'],
                                                        workdir,
                                                        pantsd_config))
        checker.assert_running(3)

        print('list')
        self.assert_success(self.run_pants_with_workdir(['list', ':'],
                                                        workdir,
                                                        pantsd_config))
        checker.assert_running(3)

        # And again using the cached BuildGraph.
        print('cached list')
        self.assert_success(self.run_pants_with_workdir(['list', '::'],
                                                        workdir,
                                                        pantsd_config))
        checker.assert_running(3)
      finally:
        for line in read_pantsd_log(workdir):
          print(line)

        # Explicitly kill pantsd (from a pantsd-launched runner).
        print('kill-pantsd')
        self.assert_success(self.run_pants_with_workdir(['kill-pantsd'], workdir, pantsd_config))

      checker.assert_stopped()

      for line in read_pantsd_log(workdir):
        print(line)

      # Assert there were no warnings or errors thrown in the pantsd log.
      for line in read_pantsd_log(workdir):
        # Ignore deprecation warning emissions.
        if 'DeprecationWarning' in line:
          continue

        self.assertNotRegexpMatches(line, r'^[WE].*')

  def test_pantsd_broken_pipe(self):
    with self.pantsd_test_context() as (workdir, pantsd_config, checker):
      # Explicitly kill any running pantsd instances for the current buildroot.
      self.assert_success(self.run_pants_with_workdir(['kill-pantsd'], workdir, pantsd_config))
      try:
        # Start pantsd implicitly via a throwaway invocation.
        self.assert_success(self.run_pants_with_workdir(['help'], workdir, pantsd_config))
        checker.await_pantsd()

        run = self.run_pants_with_workdir('help | head -1', workdir, pantsd_config, shell=True)
        self.assertNotIn('broken pipe', run.stderr_data.lower())
        checker.assert_running()
      finally:
        # Explicitly kill pantsd (from a pantsd-launched runner).
        self.assert_success(self.run_pants_with_workdir(['kill-pantsd'], workdir, pantsd_config))

      checker.assert_stopped()
