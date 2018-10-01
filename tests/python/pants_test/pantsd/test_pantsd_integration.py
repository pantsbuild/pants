# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import itertools
import os
import signal
import threading
import time
import unittest
from builtins import open, range, zip
from concurrent.futures import ThreadPoolExecutor

from pants.util.contextutil import environment_as, temporary_dir
from pants.util.dirutil import rm_rf, safe_file_dump, safe_mkdir, touch
from pants_test.pantsd.pantsd_integration_test_base import (PantsDaemonIntegrationTestBase,
                                                            full_pantsd_log, read_pantsd_log)
from pants_test.testutils.process_test_util import no_lingering_process_by_command


def launch_file_toucher(f):
  """Launch a loop to touch the given file, and return a function to call to stop and join it."""
  executor = ThreadPoolExecutor(max_workers=1)
  halt = threading.Event()

  def file_toucher():
    while not halt.isSet():
      touch(f)
      time.sleep(1)

  future = executor.submit(file_toucher)

  def join():
    halt.set()
    future.result(timeout=10)

  return join


class TestPantsDaemonIntegration(PantsDaemonIntegrationTestBase):

  def test_pantsd_compile(self):
    with self.pantsd_successful_run_context('debug') as (pantsd_run, checker, _, _):
      # This tests a deeper pantsd-based run by actually invoking a full compile.
      pantsd_run(['compile', 'examples/src/scala/org/pantsbuild/example/hello/welcome'])
      checker.assert_started()

  def test_pantsd_run(self):
    extra_config = {
      'GLOBAL': {
        # Muddies the logs with warnings: once all of the warnings in the repository
        # are fixed, this can be removed.
        'glob_expansion_failure': 'ignore',
      }
    }
    with self.pantsd_successful_run_context(
          'debug',
          extra_config=extra_config
        ) as (pantsd_run, checker, workdir, _):
      pantsd_run(['list', '3rdparty:'])
      checker.assert_started()

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

        # Check if the line begins with W or E to check if it is a warning or error line.
        self.assertNotRegexpMatches(line, r'^[WE].*')

  def test_pantsd_broken_pipe(self):
    with self.pantsd_test_context() as (workdir, pantsd_config, checker):
      run = self.run_pants_with_workdir('help | head -1', workdir, pantsd_config, shell=True)
      self.assertNotIn('broken pipe', run.stderr_data.lower())
      checker.assert_started()

  def test_pantsd_stacktrace_dump(self):
    with self.pantsd_successful_run_context() as (pantsd_run, checker, workdir, _):
      pantsd_run(['help'])
      checker.assert_started()

      os.kill(checker.pid, signal.SIGUSR2)

      # Wait for log flush.
      time.sleep(2)

      self.assertIn('Current thread 0x', '\n'.join(read_pantsd_log(workdir)))

  def test_pantsd_pantsd_runner_doesnt_die_after_failed_run(self):
    # Check for no stray pantsd-runner prcesses.
    with no_lingering_process_by_command('pantsd-runner'):
      with self.pantsd_test_context() as (workdir, pantsd_config, checker):
        # Run target that throws an exception in pants.
        self.assert_failure(
          self.run_pants_with_workdir(
            ['bundle', 'testprojects/src/java/org/pantsbuild/testproject/bundle:missing-files'],
            workdir,
            pantsd_config)
        )
        checker.assert_started()

        # Assert pantsd is in a good functional state.
        self.assert_success(self.run_pants_with_workdir(['help'], workdir, pantsd_config))
        checker.assert_running()

  def test_pantsd_lifecycle_invalidation(self):
    """Runs pants commands with pantsd enabled, in a loop, alternating between options that
    should invalidate pantsd and incur a restart and then asserts for pid consistency.
    """
    with self.pantsd_successful_run_context() as (pantsd_run, checker, _, _):
      variants = (
        ['debug', 'help'],
        ['info', 'help']
      )
      last_pid = None
      for cmd in itertools.chain(*itertools.repeat(variants, 3)):
        # Run with a CLI flag.
        pantsd_run(['-l{}'.format(cmd[0]), cmd[1]])
        next_pid = checker.assert_started()
        if last_pid is not None:
          self.assertNotEqual(last_pid, next_pid)
        last_pid = next_pid

        # Run with an env var.
        pantsd_run(cmd[1:], {'GLOBAL': {'level': cmd[0]}})
        checker.assert_running()

  def test_pantsd_lifecycle_non_invalidation(self):
    with self.pantsd_successful_run_context() as (pantsd_run, checker, _, _):
      variants = (
        ['-q', 'help'],
        ['--no-colors', 'help'],
        ['help']
      )
      last_pid = None
      for cmd in itertools.chain(*itertools.repeat(variants, 3)):
        # Run with a CLI flag.
        pantsd_run(cmd)
        next_pid = checker.assert_started()
        if last_pid is not None:
          self.assertEqual(last_pid, next_pid)
        last_pid = next_pid

  def test_pantsd_lifecycle_non_invalidation_on_config_string(self):
    with temporary_dir() as dist_dir_root, temporary_dir() as config_dir:
      config_files = [
        os.path.abspath(os.path.join(config_dir, 'pants.ini.{}'.format(i))) for i in range(2)
      ]
      for config_file in config_files:
        print('writing {}'.format(config_file))
        with open(config_file, 'w') as fh:
          fh.write('[GLOBAL]\npants_distdir: {}\n'.format(os.path.join(dist_dir_root, 'v1')))

      invalidating_config = os.path.join(config_dir, 'pants.ini.invalidates')
      with open(invalidating_config, 'w') as fh:
        fh.write('[GLOBAL]\npants_distdir: {}\n'.format(os.path.join(dist_dir_root, 'v2')))

      with self.pantsd_successful_run_context() as (pantsd_run, checker, _, _):
        variants = [['--pants-config-files={}'.format(f), 'help'] for f in config_files]
        pantsd_pid = None
        for cmd in itertools.chain(*itertools.repeat(variants, 2)):
          pantsd_run(cmd)
          if not pantsd_pid:
            pantsd_pid = checker.assert_started()
          else:
            checker.assert_running()

        pantsd_run(['--pants-config-files={}'.format(invalidating_config), 'help'])
        self.assertNotEqual(pantsd_pid, checker.assert_started())

  def test_pantsd_stray_runners(self):
    # Allow env var overrides for local stress testing.
    attempts = int(os.environ.get('PANTS_TEST_PANTSD_STRESS_ATTEMPTS', 20))
    cmd = os.environ.get('PANTS_TEST_PANTSD_STRESS_CMD', 'help').split()

    with no_lingering_process_by_command('pantsd-runner'):
      with self.pantsd_successful_run_context('debug') as (pantsd_run, checker, _, _):
        pantsd_run(cmd)
        checker.assert_started()
        for _ in range(attempts):
          pantsd_run(cmd)
          checker.assert_running()
        # The runner can sometimes exit more slowly than the thin client caller.
        time.sleep(3)

  def test_pantsd_aligned_output(self):
    # Set for pytest output display.
    self.maxDiff = None

    cmds = [
      ['goals'],
      ['help'],
      ['targets'],
      ['roots']
    ]

    non_daemon_runs = [self.run_pants(cmd) for cmd in cmds]

    with self.pantsd_successful_run_context() as (pantsd_run, checker, workdir, _):
      daemon_runs = [pantsd_run(cmd) for cmd in cmds]
      checker.assert_started()

    for cmd, run in zip(cmds, daemon_runs):
      stderr_output = run.stderr_data.strip()
      self.assertEqual(stderr_output, '', 'Non-empty stderr for {}: {}'.format(cmd, stderr_output))
      self.assertNotEqual(run.stdout_data, '', 'Empty stdout for {}'.format(cmd))

    for run_pairs in zip(non_daemon_runs, daemon_runs):
      self.assertEqual(*(run.stdout_data for run in run_pairs))

  def test_pantsd_filesystem_invalidation(self):
    """Runs with pantsd enabled, in a loop, while another thread invalidates files."""
    with self.pantsd_successful_run_context() as (pantsd_run, checker, workdir, _):
      cmd = ['list', '::']
      pantsd_run(cmd)
      checker.assert_started()

      # Launch a separate thread to poke files in 3rdparty.
      join = launch_file_toucher('3rdparty/BUILD')

      # Repeatedly re-list 3rdparty while the file is being invalidated.
      for _ in range(0, 8):
        pantsd_run(cmd)
        checker.assert_running()

      join()

  def test_pantsd_client_env_var_is_inherited_by_pantsd_runner_children(self):
    EXPECTED_VALUE = '333'
    with self.pantsd_successful_run_context() as (pantsd_run, checker, workdir, _):
      # First, launch the daemon without any local env vars set.
      pantsd_run(['help'])
      checker.assert_started()

      # Then, set an env var on the secondary call.
      with environment_as(TEST_ENV_VAR_FOR_PANTSD_INTEGRATION_TEST=EXPECTED_VALUE):
        result = pantsd_run(
          ['-q',
           'run',
           'testprojects/src/python/print_env',
           '--',
           'TEST_ENV_VAR_FOR_PANTSD_INTEGRATION_TEST']
        )
        checker.assert_running()

      self.assertEqual(EXPECTED_VALUE, ''.join(result.stdout_data).strip())

  def test_pantsd_launch_env_var_is_not_inherited_by_pantsd_runner_children(self):
    with self.pantsd_test_context() as (workdir, pantsd_config, checker):
      with environment_as(NO_LEAKS='33'):
        self.assert_success(
          self.run_pants_with_workdir(
            ['help'],
            workdir,
            pantsd_config)
        )
        checker.assert_started()

      self.assert_failure(
        self.run_pants_with_workdir(
          ['-q', 'run', 'testprojects/src/python/print_env', '--', 'NO_LEAKS'],
          workdir,
          pantsd_config
        )
      )
      checker.assert_running()

  def test_pantsd_invalidation_file_tracking(self):
    test_file = 'testprojects/src/python/print_env/main.py'
    config = {'GLOBAL': {'pantsd_invalidation_globs': '["testprojects/src/python/print_env/*"]'}}
    with self.pantsd_successful_run_context(extra_config=config) as (
      pantsd_run, checker, workdir, _
    ):
      pantsd_run(['help'])
      checker.assert_started()

      # Let any fs events quiesce.
      time.sleep(5)

      # Check the logs.
      self.assertRegexpMatches(
        full_pantsd_log(workdir),
        r'watching invalidating files:.*{}'.format(test_file)
      )

      checker.assert_running()
      touch(test_file)
      # Permit ample time for the async file event propagate in CI.
      time.sleep(10)
      checker.assert_stopped()

      self.assertIn('saw file events covered by invalidation globs', full_pantsd_log(workdir))

  def test_pantsd_pid_deleted(self):
    with self.pantsd_successful_run_context() as (pantsd_run, checker, workdir, config):
      pantsd_run(['help'])
      checker.assert_started()

      # Let any fs events quiesce.
      time.sleep(5)

      checker.assert_running()
      os.unlink(os.path.join(config["GLOBAL"]["pants_subprocessdir"], "pantsd", "pid"))

      # Permit ample time for the async file event propagate in CI.
      time.sleep(10)
      checker.assert_stopped()

  def test_pantsd_pid_change(self):
    with self.pantsd_successful_run_context() as (pantsd_run, checker, workdir, config):
      pantsd_run(['help'])
      checker.assert_started()

      # Let any fs events quiesce.
      time.sleep(5)

      checker.assert_running()

      pidpath = os.path.join(config["GLOBAL"]["pants_subprocessdir"], "pantsd", "pid")
      with open(pidpath, 'w') as f:
        f.write('9')

      # Permit ample time for the async file event propagate in CI.
      time.sleep(10)
      checker.assert_stopped()

      # Remove the pidfile so that the teardown script doesn't try to kill process 9.
      os.unlink(pidpath)

  def test_pantsd_invalidation_stale_sources(self):
    test_path = 'tests/python/pants_test/daemon_correctness_test_0001'
    test_build_file = os.path.join(test_path, 'BUILD')
    test_src_file = os.path.join(test_path, 'some_file.py')
    has_source_root_regex = r'"source_root": ".*/{}"'.format(test_path)
    export_cmd = ['export', test_path]

    try:
      with self.pantsd_successful_run_context() as (pantsd_run, checker, workdir, _):
        safe_mkdir(test_path, clean=True)

        pantsd_run(['help'])
        checker.assert_started()

        safe_file_dump(test_build_file, "python_library(sources=globs('some_non_existent_file.py'))", binary_mode=False)
        result = pantsd_run(export_cmd)
        checker.assert_running()
        self.assertNotRegexpMatches(result.stdout_data, has_source_root_regex)

        safe_file_dump(test_build_file, "python_library(sources=globs('*.py'))", binary_mode=False)
        result = pantsd_run(export_cmd)
        checker.assert_running()
        self.assertNotRegexpMatches(result.stdout_data, has_source_root_regex)

        safe_file_dump(test_src_file, 'import this\n', binary_mode=False)
        result = pantsd_run(export_cmd)
        checker.assert_running()
        self.assertRegexpMatches(result.stdout_data, has_source_root_regex)
    finally:
      rm_rf(test_path)

  def test_pantsd_parse_exception_success(self):
    # This test covers the case described in #6426, where a run that is failing fast due to an
    # exception can race other completing work. We expect all runs to fail due to the error
    # that has been introduced, but none of them should hang.
    test_path = 'testprojects/3rdparty/this_is_definitely_not_a_valid_directory'
    test_build_file = os.path.join(test_path, 'BUILD')
    invalid_symbol = 'this_is_definitely_not_a_valid_symbol'

    try:
      safe_mkdir(test_path, clean=True)
      safe_file_dump(test_build_file, "{}()".format(invalid_symbol), binary_mode=False)
      for _ in range(3):
        with self.pantsd_run_context(success=False) as (pantsd_run, checker, _, _):
          result = pantsd_run(['list', 'testprojects::'])
          checker.assert_started()
          self.assertIn(invalid_symbol, result.stderr_data)
    finally:
      rm_rf(test_path)

  def test_pantsd_multiple_parallel_runs(self):
    with self.pantsd_test_context() as (workdir, config, checker):
      file_to_make = os.path.join(workdir, 'some_magic_file')
      waiter_handle = self.run_pants_with_workdir_without_waiting(
        ['run', 'testprojects/src/python/coordinated_runs:waiter', '--', file_to_make],
        workdir,
        config,
      )

      # Wait for the python run to be running
      time.sleep(15)

      checker.assert_started()

      creator_handle = self.run_pants_with_workdir_without_waiting(
        ['run', 'testprojects/src/python/coordinated_runs:creator', '--', file_to_make],
        workdir,
        config,
      )

      self.assert_success(creator_handle.join())
      self.assert_success(waiter_handle.join())

  def test_pantsd_parent_runner_killed(self):
    with self.pantsd_test_context() as (workdir, config, checker):
      # Launch a run that will wait for a file to be created (but do not create that file).
      file_to_make = os.path.join(workdir, 'some_magic_file')
      waiter_handle = self.run_pants_with_workdir_without_waiting(
        ['run', 'testprojects/src/python/coordinated_runs:waiter', '--', file_to_make],
        workdir,
        config,
      )

      # Wait for the python run to be running.
      time.sleep(5)
      checker.assert_started()

      # Locate the single "parent" pantsd-runner process, and kill it.
      pantsd_runner_processes = [p for p in checker.runner_process_context.current_processes()
                                 if p.ppid() == 1]
      self.assertEquals(1, len(pantsd_runner_processes))
      parent_runner_process = pantsd_runner_processes[0]
      parent_runner_pid = parent_runner_process.pid
      # Send SIGTERM
      parent_runner_process.terminate()
      waiter_run = waiter_handle.join()

      # Ensure that we saw the failure in the client's stdout, and that we got a remote exception.
      self.assert_failure(waiter_run)
      self.assertRegexpMatches(waiter_run.stderr_data, """\
Signal {signum} was raised\\. Exiting with failure\\.
\\(backtrace omitted\\)
""".format(pid=parent_runner_pid, signum=signal.SIGTERM))

  def _assert_pantsd_keyboardinterrupt_signal(self, signum):
    # TODO: This tests that pantsd-runner processes actually die after the thin client receives the
    # specified signal.
    with self.pantsd_test_context() as (workdir, config, checker):
      # Launch a run that will wait for a file to be created (but do not create that file).
      file_to_make = os.path.join(workdir, 'some_magic_file')
      waiter_handle = self.run_pants_with_workdir_without_waiting(
        ['run', 'testprojects/src/python/coordinated_runs:waiter', '--', file_to_make],
        workdir,
        config,
      )

      time.sleep(5)
      checker.assert_started()

      # Get all the pantsd-runner processes while they're still around.
      pantsd_runner_processes = checker.runner_process_context.current_processes()
      # This should kill the pantsd-runner processes through the RemotePantsRunner SIGINT handler.
      os.kill(waiter_handle.process.pid, signum)
      waiter_run = waiter_handle.join()
      self.assert_failure(waiter_run)
      self.assertIn('\nInterrupted by user.\n', waiter_run.stderr_data)

      # TODO: SIGTERM should be tested as well, but the expected behavior is a little different --
      # we should test that the pantsd-runner process exits with failure (if possible -- see the
      # caveat on psutil below), and then check the remote process's fatal error log to confirm the
      # remote pantsd-runner receives a SIGTERM and dies.

      time.sleep(1)
      for proc in pantsd_runner_processes:
        # TODO: we could be checking the return codes of the subprocesses, but psutil is currently
        # limited on non-Windows hosts -- see https://psutil.readthedocs.io/en/latest/#processes.
        # The pantsd-runner processes should be dead, and they should have exited with 1.
        self.assertFalse(proc.is_running())

  @unittest.skip('TODO: this should be unskipped as part of the work for #6574!')
  def test_pantsd_control_c(self):
    self._assert_pantsd_keyboardinterrupt_signal(signal.SIGINT)

  @unittest.skip('TODO: this should be unskipped as part of the work for #6574!')
  def test_pantsd_sigquit(self):
    # We convert a local SIGQUIT in the thin client process -> SIGINT on the remote end in
    # RemotePantsRunner.
    self._assert_pantsd_keyboardinterrupt_signal(signal.SIGQUIT)

  def test_pantsd_environment_scrubbing(self):
    # This pair of JVM options causes the JVM to always crash, so the command will fail if the env
    # isn't stripped.
    with self.pantsd_successful_run_context(
      extra_config={'compile.zinc': {'jvm_options': ['-Xmx1g']}},
      extra_env={'_JAVA_OPTIONS': '-Xms2g'},
    ) as (pantsd_run, checker, workdir, _):
      pantsd_run(['help'])
      checker.assert_started()

      result = pantsd_run(['compile', 'examples/src/java/org/pantsbuild/example/hello/simple'])
      self.assert_success(result)

  def test_pantsd_unicode_environment(self):
    with self.pantsd_successful_run_context(
      extra_env={'XXX': '¡'},
    ) as (pantsd_run, checker, workdir, _):
      result = pantsd_run(['help'])
      checker.assert_started()
      self.assert_success(result)
