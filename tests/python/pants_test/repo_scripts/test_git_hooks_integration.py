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
from pants_test.pants_run_integration_test import PantsRunIntegrationTest
from pants_test.repo_scripts.git_hook_test_mixin import GitHookTestMixin


class HeaderCheckTest(PantsRunIntegrationTest, GitHookTestMixin):

  def test_check_python_headers(self):
    cur_year_num = datetime.datetime.now().year
    cur_year = str(cur_year_num)
    with self._create_tiny_git_repo() as (_, worktree, _):
      new_py_path = os.path.join(worktree, 'subdir/file.py')

      def assert_header_check(added_files, expected_excerpt):
        self._assert_subprocess_error(
          worktree=worktree,
          cmd=(['./pants', 'run', 'build-support/bin:check_header', '--',
                'subdir', '--newly-created-files'] + added_files),
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

      # Check that a file isn't checked against the current year if it is not passed as an
      # arg to the script.
      # Use the same file as last time, with last year's copyright date.
      self._assert_subprocess_success(
        worktree,
        cmd=(['./pants', 'run', 'build-support/bin:check_header', '--', 'subdir']))

      # Check that we also support Python 2-style headers (while still checking the current year's
      # copyright date!).
      safe_file_dump(new_py_path, dedent("""\
        # coding=utf-8
        # Copyright {} Pants project contributors (see CONTRIBUTORS.md).
        # Licensed under the Apache License, Version 2.0 (see LICENSE).

        from __future__ import absolute_import, division, print_function, unicode_literals

        """.format(cur_year))
      )
      self._assert_subprocess_success(
        worktree,
        cmd=(['./pants', 'run', 'build-support/bin:check_header', '--',
              'subdir', '--newly-created-files', rel_new_py_path]))

  def test_build_file_headers(self):
    self.assertTrue(False, 'TODO!')
