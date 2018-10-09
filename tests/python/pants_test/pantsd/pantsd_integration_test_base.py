# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import functools
import os
import time
from builtins import open
from contextlib import contextmanager

from colors import bold, cyan, magenta

from pants.pantsd.process_manager import ProcessManager
from pants.util.collections import recursively_update
from pants_test.pants_run_integration_test import PantsRunIntegrationTest
from pants_test.testutils.process_test_util import no_lingering_process_by_command


def banner(s):
  print(cyan('=' * 63))
  print(cyan('- {} {}'.format(s, '-' * (60 - len(s)))))
  print(cyan('=' * 63))


def read_pantsd_log(workdir):
  # Surface the pantsd log for easy viewing via pytest's `-s` (don't capture stdio) option.
  with open('{}/pantsd/pantsd.log'.format(workdir), 'r') as f:
    for line in f:
      yield line.strip()


def full_pantsd_log(workdir):
  return '\n'.join(read_pantsd_log(workdir))


class PantsDaemonMonitor(ProcessManager):
  def __init__(self, runner_process_context, metadata_base_dir=None):
    """
    :param runner_process_context: A TrackedProcessContext that can be used to inspect live
      pantsd-runner instances created in this context.
    """
    super(PantsDaemonMonitor, self).__init__(name='pantsd', metadata_base_dir=metadata_base_dir)
    self.runner_process_context = runner_process_context

  def _log(self):
    print(magenta(
      'PantsDaemonMonitor: pid is {} is_alive={}'.format(self._pid, self.is_alive()))
    )

  def assert_started(self, timeout=.1):
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
    assert self._pid is not None, 'cant assert stoppage on an unknown pid!'
    assert self.is_dead(), 'pantsd should be stopped!'
    return self._pid


class PantsDaemonIntegrationTestBase(PantsRunIntegrationTest):
  @contextmanager
  def pantsd_test_context(self, log_level='info', extra_config=None, expected_runs=1):
    with no_lingering_process_by_command('pantsd-runner') as runner_process_context:
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
            'pants_subprocessdir': pid_dir,
          }
        }
        if extra_config:
          recursively_update(pantsd_config, extra_config)
        print('>>> config: \n{}\n'.format(pantsd_config))
        checker = PantsDaemonMonitor(runner_process_context, pid_dir)
        # TODO(#6574): this should be 1, but when we kill pantsd with a signal it doesn't make sure
        # to close the run tracker -- we can easily address this by moving that cleanup into the
        # Exiter.
        self.assert_runner(workdir, pantsd_config, ['kill-pantsd'], expected_runs=1)
        try:
          yield workdir, pantsd_config, checker
        finally:
          banner('BEGIN pantsd.log')
          for line in read_pantsd_log(workdir):
            print(line)
          banner('END pantsd.log')
          self.assert_runner(
            workdir,
            pantsd_config,
            ['kill-pantsd'],
            # TODO(#6574): this should be 1, see above.
            expected_runs=1,
          )
          checker.assert_stopped()

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
        'Expected {} RunTracker run to be created per pantsd run: was {}'.format(
          expected_runs,
          runs_created,
        )
    )
    if success:
      self.assert_success(run)
    else:
      self.assert_failure(run)
    return run
