# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import datetime
import os
import unittest
from builtins import str
from contextlib import contextmanager
from textwrap import dedent

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

  def test_check_packages(self):
    package_check_script = os.path.join(self.pants_repo_root, 'build-support/bin/check_packages.sh')
    with self._create_tiny_git_repo() as (_, worktree, _):
      init_py_path = os.path.join(worktree, 'subdir/__init__.py')

      # Check that an invalid __init__.py errors.
      safe_file_dump(init_py_path, 'asdf')
      self._assert_subprocess_error(worktree, [package_check_script, 'subdir'], """\
ERROR: All '__init__.py' files should be empty or else only contain a namespace
declaration, but the following contain code:
---
subdir/__init__.py
""")

      # Check that a valid empty __init__.py succeeds.
      safe_file_dump(init_py_path, '')
      self._assert_subprocess_success(worktree, [package_check_script, 'subdir'])

      # Check that a valid __init__.py with `pkg_resources` setup succeeds.
      safe_file_dump(init_py_path, "__import__('pkg_resources').declare_namespace(__name__)")
      self._assert_subprocess_success(worktree, [package_check_script, 'subdir'])

  # TODO: consider testing the degree to which copies (-C) and moves (-M) are detected by making
  # some small edits to a file, then moving it, and seeing if it is detected as a new file! That's
  # more testing git functionality, but since it's not clear how this is measured, it could be
  # useful if correctly detecting copies and moves ever becomes a concern.
  def test_added_files_correctly_detected(self):
    get_added_files_script = os.path.join(self.pants_repo_root,
                                          'build-support/bin/get_added_files.sh')
    with self._create_tiny_git_repo() as (git, worktree, _):
      # Create a new file.
      new_file = os.path.join(worktree, 'wow.txt')
      safe_file_dump(new_file, '')
      # Stage the file.
      rel_new_file = os.path.relpath(new_file, worktree)
      git.add(rel_new_file)
      self._assert_subprocess_success_with_output(
        worktree, [get_added_files_script],
        # This should be the only entry in the index, and it is a newly added file.
        full_expected_output="{}\n".format(rel_new_file))

  def test_check_headers(self):
    header_check_script = os.path.join(
      self.pants_repo_root, 'build-support/bin/check_header.py'
    )
    cur_year_num = datetime.datetime.now().year
    cur_year = str(cur_year_num)
    with self._create_tiny_git_repo() as (_, worktree, _):
      new_py_path = os.path.join(worktree, 'subdir/file.py')

      def assert_header_check(added_files, expected_excerpt):
        self._assert_subprocess_error(
          worktree=worktree,
          cmd=[header_check_script, 'subdir', '--files-added'] + added_files,
          expected_excerpt=expected_excerpt
        )

      # Check that a file with an empty header fails.
      safe_file_dump(new_py_path, '')
      assert_header_check(
        added_files=[],
        expected_excerpt="subdir/file.py: missing the expected header"
      )

      # Check that a file with a random header fails.
      safe_file_dump(new_py_path, 'asdf')
      assert_header_check(
        added_files=[],
        expected_excerpt="subdir/file.py: missing the expected header"
      )

      # Check that a file with a typo in the header fails
      safe_file_dump(new_py_path, dedent("""\
        # Copyright {} Pants project contributors (see CONTRIBUTORS.md).
        # Licensed under the MIT License, Version 3.3 (see LICENSE).

        """.format(cur_year))
      )
      assert_header_check(
        added_files=[],
        expected_excerpt="subdir/file.py: header does not match the expected header"
      )

      # Check that a file without a valid copyright year fails.
      safe_file_dump(new_py_path, dedent("""\
        # Copyright YYYY Pants project contributors (see CONTRIBUTORS.md).
        # Licensed under the Apache License, Version 2.0 (see LICENSE).

        """)
      )
      assert_header_check(
        added_files=[],
        expected_excerpt=(
          r"subdir/file.py: copyright year must match '20\d\d' (was YYYY): "
          "current year is {}".format(cur_year)
        )
      )

      # Check that a newly added file must have the current year.
      last_year = str(cur_year_num - 1)
      safe_file_dump(new_py_path, dedent("""\
        # Copyright {} Pants project contributors (see CONTRIBUTORS.md).
        # Licensed under the Apache License, Version 2.0 (see LICENSE).

        """.format(last_year))
      )
      rel_new_py_path = os.path.relpath(new_py_path, worktree)
      assert_header_check(
        added_files=[rel_new_py_path],
        expected_excerpt="subdir/file.py: copyright year must be {} (was {})".format(cur_year, last_year)
      )

      # Check that we also support Python 2-style headers.
      safe_file_dump(new_py_path, dedent("""\
        # coding=utf-8
        # Copyright {} Pants project contributors (see CONTRIBUTORS.md).
        # Licensed under the Apache License, Version 2.0 (see LICENSE).

        from __future__ import absolute_import, division, print_function, unicode_literals

        """.format(cur_year))
      )
      self._assert_subprocess_success(worktree, [header_check_script, 'subdir'])

      # Check that a file isn't checked against the current year if it is not passed as an
      # arg to the script.
      # Use the same file as last time, with last year's copyright date.
      self._assert_subprocess_success(worktree, [header_check_script, 'subdir'])
