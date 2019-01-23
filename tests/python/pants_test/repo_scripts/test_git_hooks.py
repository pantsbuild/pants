# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import datetime
import os
import unittest
from builtins import str
from contextlib import contextmanager

from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_file_dump, touch
from pants.util.process_handler import subprocess
from pants_test.testutils.git_util import get_repo_root, initialize_repo


class PreCommitHookTest(unittest.TestCase):

  def setUp(self):
    self.pants_repo_root = get_repo_root()

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
    with self.assertRaises(subprocess.CalledProcessError) as cm:
      subprocess.check_output(cmd, cwd=worktree)
    self.assertIn(expected_excerpt, cm.exception.output.decode('utf-8'))

  def _assert_subprocess_success(self, worktree, cmd, **kwargs):
    self.assertEqual(0, subprocess.check_call(cmd, cwd=worktree, **kwargs))

  def _assert_subprocess_success_with_output(self, worktree, cmd, full_expected_output):
    output = subprocess.check_output(cmd, cwd=worktree)
    self.assertEqual(full_expected_output, output.decode('utf-8'))

  def _assert_subprocess_error_with_input(self, worktree, cmd, input, expected_excerpt):
    proc = subprocess.Popen(
      cmd,
      cwd=worktree,
      stdin=subprocess.PIPE,
      stdout=subprocess.PIPE,
      stderr=subprocess.PIPE,
    )
    (stdout_data, stderr_data) = proc.communicate(input=input)
    self.assertNotEqual(0, proc.returncode)
    all_output = '{}\n{}'.format(stdout_data, stderr_data)
    self.assertIn(expected_excerpt, all_output.decode('utf-8'))

  def test_check_packages(self):
    package_check_script = os.path.join(self.pants_repo_root, 'build-support/bin/check_packages.sh')
    with self._create_tiny_git_repo() as (_, worktree, _):
      init_py_path = os.path.join(worktree, 'subdir/__init__.py')

      # Check that an invalid __init__.py errors.
      safe_file_dump(init_py_path, 'asdf', mode='w')
      self._assert_subprocess_error(worktree, [package_check_script, 'subdir'], """\
ERROR: All '__init__.py' files should be empty or else only contain a namespace
declaration, but the following contain code:
---
subdir/__init__.py
""")

      # Check that a valid empty __init__.py succeeds.
      safe_file_dump(init_py_path, '', mode='w')
      self._assert_subprocess_success(worktree, [package_check_script, 'subdir'])

      # Check that a valid __init__.py with `pkg_resources` setup succeeds.
      safe_file_dump(init_py_path,
                     "__import__('pkg_resources').declare_namespace(__name__)",
                     mode='w')
      self._assert_subprocess_success(worktree, [package_check_script, 'subdir'])

  # TODO: consider testing the degree to which copies (-C) and moves (-M) are detected by making
  # some small edits to a file, then moving it, and seeing if it is detected as a new file!
  def test_added_files_correctly_detected(self):
    get_added_files_script = os.path.join(self.pants_repo_root,
                                          'build-support/bin/get_added_files.sh')
    with self._create_tiny_git_repo() as (git, worktree, _):
      # Create a new file.
      new_file = os.path.join(worktree, 'wow.txt')
      safe_file_dump(new_file, '', mode='w')
      # Stage the file.
      rel_new_file = os.path.relpath(new_file, worktree)
      git.add(rel_new_file)
      self._assert_subprocess_success_with_output(
        worktree, [get_added_files_script],
        # This should be the only entry in the index, and it is a newly added file.
        full_expected_output="{}\n".format(rel_new_file))

  def test_check_headers(self):
    header_check_script = os.path.join(self.pants_repo_root,
                                       'build-support/bin/check_header_helper.py')
    with self._create_tiny_git_repo() as (_, worktree, _):
      new_py_path = os.path.join(worktree, 'subdir/file.py')

      def assert_header_check(added_files, expected_excerpt):
        added_files_process_input = '\n'.join(added_files)
        self._assert_subprocess_error_with_input(
          worktree, [header_check_script, 'subdir'],
          # The python process reads from stdin, so we have to explicitly pass an empty string in
          # order to close it.
          input='{}\n'.format(added_files_process_input) if added_files_process_input else '',
          expected_excerpt=expected_excerpt)

      # Check that a file with an empty header fails.
      safe_file_dump(new_py_path, '', mode='w')
      assert_header_check(added_files=[], expected_excerpt="""\
subdir/file.py: failed to parse header at all
""")

      # Check that a file with a random header fails.
      safe_file_dump(new_py_path, 'asdf', mode='w')
      assert_header_check(added_files=[], expected_excerpt="""\
subdir/file.py: failed to parse header at all
""")

      # Check that a file without a valid copyright year fails.
      cur_year_num = datetime.datetime.now().year
      cur_year = str(cur_year_num)
      safe_file_dump(new_py_path, """\
# coding=utf-8
# Copyright YYYY Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

""", mode='w')
      assert_header_check(added_files=[], expected_excerpt="""\
subdir/file.py: copyright year must match '20\\d\\d' (was YYYY): current year is {}
""".format(cur_year))

      # Check that a file read from stdin is checked against the current year.
      last_year = str(cur_year_num - 1)
      safe_file_dump(new_py_path, """\
# coding=utf-8
# Copyright {} Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

""".format(last_year),
                     mode='w')
      rel_new_py_path = os.path.relpath(new_py_path, worktree)
      assert_header_check(added_files=[rel_new_py_path], expected_excerpt="""\
subdir/file.py: copyright year must be {} (was {})
""".format(cur_year, last_year))

      # Check that a file read from stdin isn't checked against the current year if
      # PANTS_IGNORE_ADDED_FILES is set.
      # Use the same file as last time, with last year's copyright date.
      self._assert_subprocess_success(worktree, [header_check_script, 'subdir'],
                                      env={'PANTS_IGNORE_ADDED_FILES': 'y'})
