# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import shutil
import subprocess
import unittest
from contextlib import contextmanager
from pathlib import Path
from typing import Optional, Sequence

from pants.testutil.git_util import initialize_repo
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_file_dump, safe_mkdir_for


class PreCommitHookTest(unittest.TestCase):
    @contextmanager
    def _create_tiny_git_repo(self, *, copy_files: Optional[Sequence[Path]] = None):
        with temporary_dir() as gitdir, temporary_dir() as worktree:
            # A tiny little fake git repo we will set up. initialize_repo() requires at least one file.
            Path(worktree, "README").touch()
            # The contextmanager interface is only necessary if an explicit gitdir is not provided.
            with initialize_repo(worktree, gitdir=gitdir) as git:
                if copy_files is not None:
                    for fp in copy_files:
                        new_fp = Path(worktree, fp)
                        safe_mkdir_for(str(new_fp))
                        shutil.copy(fp, new_fp)
                yield git, worktree, gitdir

    def _assert_subprocess_error(self, worktree, cmd, expected_excerpt):
        result = subprocess.run(
            cmd, cwd=worktree, stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8",
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn(expected_excerpt, f"{result.stdout}\n{result.stderr}")

    def _assert_subprocess_success(self, worktree, cmd, **kwargs):
        self.assertEqual(0, subprocess.check_call(cmd, cwd=worktree, **kwargs))

    def _assert_subprocess_success_with_output(self, worktree, cmd, full_expected_output):
        stdout = subprocess.run(
            cmd, cwd=worktree, check=True, stdout=subprocess.PIPE, encoding="utf-8"
        ).stdout
        self.assertEqual(full_expected_output, stdout)

    def test_check_packages(self):
        package_check_script = "build-support/bin/check_packages.sh"
        with self._create_tiny_git_repo(copy_files=[Path(package_check_script)]) as (
            _,
            worktree,
            _,
        ):
            init_py_path = os.path.join(worktree, "subdir/__init__.py")

            # Check that an invalid __init__.py errors.
            safe_file_dump(init_py_path, "asdf")
            self._assert_subprocess_error(
                worktree,
                [package_check_script, "subdir"],
                """\
ERROR: All '__init__.py' files should be empty or else only contain a namespace
declaration, but the following contain code:
---
subdir/__init__.py
""",
            )

            # Check that a valid empty __init__.py succeeds.
            safe_file_dump(init_py_path, "")
            self._assert_subprocess_success(worktree, [package_check_script, "subdir"])

            # Check that a valid __init__.py with `pkg_resources` setup succeeds.
            safe_file_dump(init_py_path, '__import__("pkg_resources").declare_namespace(__name__)')
            self._assert_subprocess_success(worktree, [package_check_script, "subdir"])
