# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.util.process_handler import subprocess
from pants.util.strutil import ensure_binary
from pants_test.test_base import TestBase
from pants_test.testutils.git_util import get_repo_root


class RepoScriptTestBase(TestBase):

  def setUp(self):
    self.pants_repo_root = get_repo_root()

  def _assert_subprocess_error(self, worktree, cmd, expected_output, **kwargs):
    with self.assertRaises(subprocess.CalledProcessError) as cm:
      subprocess.check_output(cmd, cwd=worktree, stderr=subprocess.STDOUT, **kwargs)
    # Checks for an exact match of the combined stdout and stderr.
    self.assertEqual(expected_output, cm.exception.output.decode('utf-8'))

  def _assert_subprocess_error_excerpt(self, worktree, cmd, expected_excerpt, **kwargs):
    with self.assertRaises(subprocess.CalledProcessError) as cm:
      subprocess.check_output(cmd, cwd=worktree, stderr=subprocess.STDOUT, **kwargs)
    # NB: checks for a string contained in the combined stdout and stderr, not an exact match!
    self.assertIn(expected_excerpt, cm.exception.output.decode('utf-8'))

  def _assert_subprocess_success(self, worktree, cmd, **kwargs):
    self.assertEqual(0, subprocess.check_call(cmd, cwd=worktree, **kwargs))

  def _assert_subprocess_success_with_output(self, worktree, cmd, full_expected_output):
    output = subprocess.check_output(cmd, cwd=worktree)
    self.assertEqual(full_expected_output, output.decode('utf-8'))

  def _assert_subprocess_error_with_input(self, worktree, cmd, stdin_payload, expected_excerpt):
    proc = subprocess.Popen(
      cmd,
      cwd=worktree,
      stdin=subprocess.PIPE,
      stdout=subprocess.PIPE,
      stderr=subprocess.PIPE,
    )
    (stdout_data, stderr_data) = proc.communicate(input=ensure_binary(stdin_payload))
    # Attempting to call '{}\n{}'.format(...) on bytes in python 3 gives you the string:
    #   "b'<the first string>'\nb'<the second string>'"
    # So we explicitly decode both stdout and stderr here.
    stdout_data = stdout_data.decode('utf-8')
    stderr_data = stderr_data.decode('utf-8')
    self.assertNotEqual(0, proc.returncode)
    all_output = '{}\n{}'.format(stdout_data, stderr_data)
    self.assertIn(expected_excerpt, all_output)
