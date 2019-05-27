# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import datetime
import os
import unittest
from builtins import object, str
from contextlib import contextmanager
from textwrap import dedent

from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_file_dump, touch
from pants.util.process_handler import subprocess
from pants_test.testutils.git_util import get_repo_root, initialize_repo


class GitHookTestMixin(object):

  @contextmanager
  def _create_tiny_git_repo(self):
    with temporary_dir() as gitdir,\
         temporary_dir() as worktree:
      # A tiny little fake git repo we will set up. initialize_repo() requires at least one file.
      readme_file = os.path.join(worktree, 'README')
      touch(readme_file)
      # The contextmanager interface is only necessary if an explicit gitdir is not provided.
      with initialize_repo(worktree, gitdir=gitdir) as git:
        yield git, worktree, gitdir

  def _assert_subprocess_error(self, worktree, cmd, expected_excerpt):
    proc = subprocess.Popen(
      cmd,
      cwd=worktree,
      stdout=subprocess.PIPE,
      stderr=subprocess.PIPE,
    )
    (stdout_data, stderr_data) = proc.communicate()
    stdout_data = stdout_data.decode('utf-8')
    stderr_data = stderr_data.decode('utf-8')
    self.assertNotEqual(0, proc.returncode)
    all_output = '{}\n{}'.format(stdout_data, stderr_data)
    self.assertIn(expected_excerpt, all_output)

  def _assert_subprocess_success(self, worktree, cmd, **kwargs):
    self.assertEqual(0, subprocess.check_call(cmd, cwd=worktree, **kwargs))

  def _assert_subprocess_success_with_output(self, worktree, cmd, full_expected_output):
    output = subprocess.check_output(cmd, cwd=worktree)
    self.assertEqual(full_expected_output, output.decode('utf-8'))
