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
from pants_test.repo_scripts.git_hook_test_mixin import GitHookTestMixin


class PreCommitHookTest(unittest.TestCase, GitHookTestMixin):

  def setUp(self):
    self.pants_repo_root = get_repo_root()

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
