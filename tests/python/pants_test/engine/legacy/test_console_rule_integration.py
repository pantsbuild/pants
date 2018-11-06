# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
import time

from pants.base.build_environment import get_buildroot
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import fast_relpath, safe_file_dump
from pants_test.pants_run_integration_test import ensure_daemon
from pants_test.pantsd.pantsd_integration_test_base import PantsDaemonIntegrationTestBase


class TestConsoleRuleIntegration(PantsDaemonIntegrationTestBase):

  @ensure_daemon
  def test_v2_list(self):
    result = self.do_command(
      '--no-v1',
      '--v2',
      'list',
      '::',
      success=True
    )

    output_lines = result.stdout_data.splitlines()
    self.assertGreater(len(output_lines), 1000)
    self.assertIn('3rdparty/python:psutil', output_lines)

  def test_v2_list_does_not_cache(self):
    with self.pantsd_successful_run_context() as (runner, checker, workdir, pantsd_config):
      def run_list():
        command = ['--no-v1',
                   '--v2',
                   'list',
                   'src/::',]

        result = runner(command)
        checker.assert_started()
        return result

      first_run = run_list().stdout_data.splitlines()
      second_run = run_list().stdout_data.splitlines()
      self.assertTrue(sorted(first_run), sorted(second_run))

  @ensure_daemon
  def test_v2_goal_validation(self):
    result = self.do_command(
      '--no-v1',
      '--v2',
      'lint',
      '::',
      success=False
    )

    self.assertIn(
      'could not satisfy the following goals with @console_rules: lint',
      result.stderr_data
    )

  @ensure_daemon
  def test_v2_goal_validation_both(self):
    self.do_command(
      '--v1',
      '--v2',
      'filedeps',
      ':',
      success=True
    )

  def test_v2_list_loop(self):
    # Create a BUILD file in a nested temporary directory, and add additional targets to it.
    with self.pantsd_test_context() as (workdir, config, checker), \
        temporary_dir(root_dir=get_buildroot()) as tmpdir:
      rel_tmpdir = fast_relpath(tmpdir, get_buildroot())

      def dump(content):
        safe_file_dump(os.path.join(tmpdir, 'BUILD'), content, mode="w")

      # Dump an initial target before starting the loop.
      dump('target(name="one")')

      # Launch the loop as a background process.
      handle = self.run_pants_with_workdir_without_waiting(
        [
          '--no-v1',
          '--v2',
          '--loop',
          '--loop-max=3',
          'list',
          '{}:'.format(tmpdir),
        ],
        workdir,
        config,
      )

      # Wait for the loop to stabilize.
      time.sleep(10)
      checker.assert_started()

      # Replace the BUILD file content twice.
      dump('target(name="two")')
      time.sleep(5)
      dump('target(name="three")')

      # Verify that the three different target states were listed, and that the process exited.
      pants_result = handle.join()
      self.assert_success(pants_result)
      self.assertEquals(
          ['{}:{}'.format(rel_tmpdir, name) for name in ('one', 'two', 'three')],
          list(pants_result.stdout_data.splitlines())
        )
