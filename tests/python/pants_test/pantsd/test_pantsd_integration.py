# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import functools
import itertools
import os
import signal
import time
from contextlib import contextmanager

from pants.pantsd.process_manager import ProcessManager
from pants.util.collections import combined_dict
from pants_test.pants_run_integration_test import PantsRunIntegrationTest
from pants_test.testutils.process_test_util import check_process_exists_by_command


class PantsDaemonMonitor(ProcessManager):
  def __init__(self, metadata_base_dir=None):
    super(PantsDaemonMonitor, self).__init__(name='pantsd', metadata_base_dir=metadata_base_dir)

  def _log(self):
    print('PantsDaemonMonitor: pid is {} is_alive={}'.format(self._pid, self.is_alive()))

  def await_pantsd(self, timeout=3):
    self._process = None
    self._pid = self.await_pid(timeout)
    self.assert_running()
    return self._pid

  def assert_running(self):
    self._log()
    assert self._pid is not None and self.is_alive(), 'pantsd should be running!'
    return self._pid

  def assert_stopped(self):
    self._log()
    assert self._pid is not None and self.is_dead(), 'pantsd should be stopped!'
    return self._pid


def banner(s):
  print('=' * 63)
  print('- {} {}'.format(s, '-' * (60 - len(s))))
  print('=' * 63)


def read_pantsd_log(workdir):
  # Surface the pantsd log for easy viewing via pytest's `-s` (don't capture stdio) option.
  with open('{}/pantsd/pantsd.log'.format(workdir)) as f:
    for line in f:
      yield line.strip()


class TestPantsDaemonIntegration(PantsRunIntegrationTest):
  @contextmanager
  def pantsd_test_context(self, log_level='info'):
    with self.temporary_workdir() as workdir_base:
      pid_dir = os.path.join(workdir_base, '.pids')
      workdir = os.path.join(workdir_base, '.workdir.pants.d')
      print('\npantsd log is {}/pantsd/pantsd.log'.format(workdir))
      pantsd_config = {
        'GLOBAL': {
          'enable_pantsd': True,
          # The absolute paths in CI can exceed the UNIX socket path limitation
          # (>104-108 characters), so we override that here with a shorter path.
          'watchman_socket_path': '/tmp/watchman.{}.sock'.format(os.getpid()),
          'level': log_level,
          'pants_subprocessdir': pid_dir
        }
      }
      checker = PantsDaemonMonitor(pid_dir)
      self.assert_success_runner(workdir, pantsd_config, ['kill-pantsd'])
      try:
        yield workdir, pantsd_config, checker
      finally:
        banner('BEGIN pantsd.log')
        for line in read_pantsd_log(workdir):
          print(line)
        banner('END pantsd.log')
        self.assert_success_runner(workdir, pantsd_config, ['kill-pantsd'])
        checker.assert_stopped()

  @contextmanager
  def pantsd_successful_run_context(self, log_level='info'):
    with self.pantsd_test_context(log_level) as (workdir, pantsd_config, checker):
      yield (
        functools.partial(
          self.assert_success_runner,
          workdir,
          pantsd_config
        ),
        checker,
        workdir
      )

  def assert_success_runner(self, workdir, config, cmd, extra_config={}):
    print('running: ./pants {} (extra_config={})'.format(' '.join(cmd), extra_config))
    return self.assert_success(
      self.run_pants_with_workdir(cmd, workdir, combined_dict(config, extra_config))
    )

  def test_pantsd_compile(self):
    with self.pantsd_successful_run_context('debug') as (pantsd_run, checker, workdir):
      # This tests a deeper pantsd-based run by actually invoking a full compile.
      pantsd_run(['compile', 'examples/src/scala/org/pantsbuild/example/hello/welcome'])
      checker.await_pantsd()

  def test_pantsd_run(self):
    with self.pantsd_successful_run_context('debug') as (pantsd_run, checker, workdir):
      pantsd_run(['list', '3rdparty:'])
      checker.await_pantsd()

      pantsd_run(['list', ':'])
      checker.assert_running()

      pantsd_run(['list', '::'])
      checker.assert_running()

      # And again using the cached BuildGraph.
      pantsd_run(['list', '::'])
      checker.assert_running()

      # Assert there were no warnings or errors thrown in the pantsd log.
      for line in read_pantsd_log(workdir):
        # Ignore deprecation warning emissions.
        if 'DeprecationWarning' in line:
          continue

        self.assertNotRegexpMatches(line, r'^[WE].*')

  def test_pantsd_broken_pipe(self):
    with self.pantsd_test_context() as (workdir, pantsd_config, checker):
      run = self.run_pants_with_workdir('help | head -1', workdir, pantsd_config, shell=True)
      self.assertNotIn('broken pipe', run.stderr_data.lower())
      checker.await_pantsd()

  def test_pantsd_stacktrace_dump(self):
    with self.pantsd_successful_run_context() as (pantsd_run, checker, workdir):
      pantsd_run(['help'])
      checker.await_pantsd()

      os.kill(checker.pid, signal.SIGUSR2)

      # Wait for log flush.
      time.sleep(2)

      self.assertIn('Current thread 0x', '\n'.join(read_pantsd_log(workdir)))

  def test_pantsd_pantsd_runner_doesnt_die_after_failed_run(self):
    with self.pantsd_test_context() as (workdir, pantsd_config, checker):
      # Run target that throws an exception in pants.
      self.assert_failure(
        self.run_pants_with_workdir(
          ['bundle', 'testprojects/src/java/org/pantsbuild/testproject/bundle:missing-files'],
          workdir,
          pantsd_config)
      )
      checker.await_pantsd()

      # Check for no stray pantsd-runner prcesses.
      self.assertFalse(check_process_exists_by_command('pantsd-runner'))

      # Assert pantsd is in a good functional state.
      self.assert_success(self.run_pants_with_workdir(['help'], workdir, pantsd_config))
      checker.assert_running()

  def test_pantsd_lifecycle_invalidation(self):
    """Runs pants commands with pantsd enabled, in a loop, alternating between options that
    should invalidate pantsd and incur a restart and then asserts for pid consistency.
    """
    with self.pantsd_successful_run_context() as (pantsd_run, checker, workdir):
      variants = (
        ['debug', 'help'],
        ['info', 'help']
      )
      last_pid = None
      for cmd in itertools.chain(*itertools.repeat(variants, 3)):
        # Run with a CLI flag.
        pantsd_run(['-l{}'.format(cmd[0]), cmd[1]])
        next_pid = checker.await_pantsd()
        if last_pid is not None:
          self.assertNotEqual(last_pid, next_pid)
        last_pid = next_pid

        # Run with an env var.
        pantsd_run(cmd[1:], {'GLOBAL': {'level': cmd[0]}})
        checker.assert_running()
