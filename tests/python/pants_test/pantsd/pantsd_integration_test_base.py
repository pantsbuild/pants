# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import functools
import os
import time
from contextlib import contextmanager

import psutil
from colors import bold, cyan, magenta

from pants.pantsd.process_manager import ProcessManager
from pants.util.collections import recursively_update
from pants_test.pants_run_integration_test import PantsRunIntegrationTest, read_pantsd_log
from pants_test.testutils.process_test_util import no_lingering_process_by_command


def banner(s):
  print(cyan('=' * 63))
  print(cyan('- {} {}'.format(s, '-' * (60 - len(s)))))
  print(cyan('=' * 63))


class PantsDaemonMonitor(ProcessManager):
  def __init__(self, runner_process_context, metadata_base_dir=None):
    """
    :param runner_process_context: A TrackedProcessContext that can be used to inspect live
      pantsd instances created in this context.
    """
    super(PantsDaemonMonitor, self).__init__(name='pantsd', metadata_base_dir=metadata_base_dir)
    self.runner_process_context = runner_process_context

  def _log(self):
    print(magenta(
      'PantsDaemonMonitor: pid is {} is_alive={}'.format(self._pid, self.is_alive()))
    )

  # TODO(#7330): Determine why pantsd takes so long to start! Waiting for
  # 'testprojects/src/python/coordinated_runs:waiter' specifically seems to require this 16-second
  # timeout.
  def assert_started(self, timeout=16):
    self._process = None
    self._pid = self.await_pid(timeout)
    self._check_pantsd_is_alive()
    return self._pid

  def assert_pantsd_runner_started(self, client_pid, timeout=12):
    return self.await_metadata_by_name(
      name='nailgun-client',
      metadata_key=str(client_pid),
      timeout=timeout,
      caster=int,
    )

  def _check_pantsd_is_alive(self):
    self._log()
    assert self._pid is not None and self.is_alive(), 'cannot assert that pantsd is running. Try calling assert_started before calling this method.'
    return self._pid

  def current_memory_usage(self):
    """Return the current memory usage of the pantsd process (which must be running)

    :return: memory usage in bytes
    """
    self.assert_running()
    return psutil.Process(self._pid).memory_info()[0]

  def assert_running(self):
    if not self._pid:
      return self.assert_started()
    else:
      return self._check_pantsd_is_alive()

  def assert_stopped(self):
    self._log()
    assert self._pid is not None, 'cannot assert pantsd stoppage. Try calling assert_started before calling this method.'
    assert self.is_dead(), 'pantsd should be stopped!'
    return self._pid


class PantsDaemonIntegrationTestBase(PantsRunIntegrationTest):

  @classmethod
  def use_pantsd_env_var(cls):
    """We set our own ad-hoc pantsd configuration in most of these tests"""
    return False

  @contextmanager
  def pantsd_test_context(self, log_level='info', extra_config=None):
    with no_lingering_process_by_command('pantsd') as runner_process_context:
      with self.temporary_workdir() as workdir_base:
        pid_dir = os.path.join(workdir_base, '.pids')
        workdir = os.path.join(workdir_base, '.workdir.pants.d')
        print('\npantsd log is {}/pantsd/pantsd.log'.format(workdir))
        pantsd_config = {
          'GLOBAL': {
            'enable_pantsd': True,
            'shutdown_pantsd_after_run': False,
            # The absolute paths in CI can exceed the UNIX socket path limitation
            # (>104-108 characters), so we override that here with a shorter path.
            'watchman_socket_path': '/tmp/watchman.{}.sock'.format(os.getpid()),
            'level': log_level,
            'pants_subprocessdir': pid_dir,
          }
        }

        if extra_config:
          recursively_update(pantsd_config, extra_config)
        print('>>> config: \n{}\n'.format(pantsd_config))

        checker = PantsDaemonMonitor(runner_process_context, pid_dir)
        self.assert_runner(workdir, pantsd_config, ['kill-pantsd'], expected_runs=1)
        try:
          yield workdir, pantsd_config, checker
          self.assert_runner(
            workdir,
            pantsd_config,
            ['kill-pantsd'],
            expected_runs=1,
          )
          checker.assert_stopped()
        finally:
          banner('BEGIN pantsd.log')
          for line in read_pantsd_log(workdir):
            print(line)
          banner('END pantsd.log')

  @contextmanager
  def pantsd_successful_run_context(self, *args, **kwargs):
    with self.pantsd_run_context(*args, success=True, **kwargs) as context:
      yield context

  @contextmanager
  def pantsd_run_context(self, log_level='info', extra_config=None, extra_env=None, success=True,
                         no_track_run_counts=False):
    with self.pantsd_test_context(log_level, extra_config) as (workdir, pantsd_config, checker):
      yield (
        functools.partial(
          self.assert_runner,
          workdir,
          pantsd_config,
          extra_env=extra_env,
          success=success,
        ),
        checker,
        workdir,
        pantsd_config,
      )

  def _run_count(self, workdir):
    run_tracker_dir = os.path.join(workdir, 'run-tracker')
    if os.path.isdir(run_tracker_dir):
      return len([f for f in os.listdir(run_tracker_dir) if f != 'latest'])
    else:
      return 0

  def assert_runner(self, workdir, config, cmd, extra_config={}, extra_env={}, expected_runs=1, success=True):
    combined_config = config.copy()
    recursively_update(combined_config, extra_config)
    print(bold(cyan('\nrunning: ./pants {} (config={}) (extra_env={})'
                    .format(' '.join(cmd), combined_config, extra_env))))
    run_count = self._run_count(workdir)
    start_time = time.time()
    run = self.run_pants_with_workdir(
      cmd,
      workdir,
      combined_config,
      extra_env=extra_env,
      # TODO: With this uncommented, `test_pantsd_run` fails.
      # tee_output=True
    )
    elapsed = time.time() - start_time
    print(bold(cyan('\ncompleted in {} seconds'.format(elapsed))))

    # TODO: uncomment this and add an issue link!
    runs_created = self._run_count(workdir) - run_count
    self.assertEqual(
        runs_created,
        expected_runs,
        'Expected {} RunTracker run(s) to be created per pantsd run: was {}'.format(
          expected_runs,
          runs_created,
        )
    )
    if success:
      self.assert_success(run)
    else:
      self.assert_failure(run)
    return run
