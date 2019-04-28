# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
from textwrap import dedent

from colors import red

from pants.util.contextutil import temporary_dir
from pants.util.dirutil import chmod_plus_x, safe_file_dump
from pants.util.strutil import create_path_env_var
from pants_test.repo_scripts.repo_script_test_base import RepoScriptTestBase


class PantsBootstrapTest(RepoScriptTestBase):

  def test_invalid_py_env_var(self):
    self._assert_subprocess_error(
      self.pants_repo_root,
      ['./pants'],
      env={'PY': 'this-is-not-a-real-python-executable'},
      expected_output='\n{}\n'.format(red(dedent("""\
        Executable this-is-not-a-real-python-executable must be discoverable on the PATH for pants to bootstrap itself in this repo.
        Exiting."""))))

  def test_invalid_gcc(self):
    with temporary_dir() as tmp_gcc_bin_dir:
      dummy_gcc_script = os.path.join(tmp_gcc_bin_dir, 'gcc')
      safe_file_dump(dummy_gcc_script, mode='w', payload=dedent("""\
        #!/usr/bin/env bash

        echo 'failure' >&2
        exit 1
        """))
      chmod_plus_x(dummy_gcc_script)
      # import pdb; pdb.set_trace()
      self._assert_subprocess_error_excerpt(
        self.pants_repo_root,
        ["./pants"],
        env={'PATH': create_path_env_var([tmp_gcc_bin_dir], env=os.environ, prepend=True)},
        expected_excerpt=dedent("""\
          Output was:
          failure

          ERROR: unable to execute 'gcc'. Please verify that your compiler is installed, in your
          $PATH and functional.
          """))
