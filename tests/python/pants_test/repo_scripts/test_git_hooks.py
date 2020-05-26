# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import datetime
import os
import shutil
import subprocess
import unittest
from contextlib import contextmanager
from pathlib import Path
from textwrap import dedent
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

    # TODO: consider testing the degree to which copies (-C) and moves (-M) are detected by making
    # some small edits to a file, then moving it, and seeing if it is detected as a new file! That's
    # more testing git functionality, but since it's not clear how this is measured, it could be
    # useful if correctly detecting copies and moves ever becomes a concern.
    def test_added_files_correctly_detected(self):
        get_added_files_script = "build-support/bin/get_added_files.sh"
        with self._create_tiny_git_repo(copy_files=[Path(get_added_files_script)]) as (
            git,
            worktree,
            _,
        ):
            # Create a new file.
            new_file = os.path.join(worktree, "wow.txt")
            safe_file_dump(new_file, "")
            # Stage the file.
            rel_new_file = os.path.relpath(new_file, worktree)
            git.add(rel_new_file)
            self._assert_subprocess_success_with_output(
                worktree,
                [get_added_files_script],
                # This should be the only entry in the index, and it is a newly added file.
                full_expected_output=f"{rel_new_file}\n",
            )

    def test_check_headers(self):
        header_check_script = "build-support/bin/check_header.py"
        cur_year_num = datetime.datetime.now().year
        cur_year = str(cur_year_num)
        with self._create_tiny_git_repo(
            copy_files=[Path(header_check_script), "build-support/bin/common.py"]
        ) as (_, worktree, _):
            new_py_path = os.path.join(worktree, "subdir/file.py")

            def assert_header_check(added_files, expected_excerpt):
                self._assert_subprocess_error(
                    worktree=worktree,
                    cmd=[header_check_script, "subdir", "--files-added"] + added_files,
                    expected_excerpt=expected_excerpt,
                )

            # Check that a file with an empty header fails.
            safe_file_dump(new_py_path, "")
            assert_header_check(
                added_files=[], expected_excerpt="subdir/file.py: missing the expected header"
            )

            # Check that a file with a random header fails.
            safe_file_dump(new_py_path, "asdf")
            assert_header_check(
                added_files=[], expected_excerpt="subdir/file.py: missing the expected header"
            )

            # Check that a file with a typo in the header fails
            safe_file_dump(
                new_py_path,
                dedent(
                    f"""\
                    # Copyright {cur_year} Pants project contributors (see CONTRIBUTORS.md).
                    # Licensed under the MIT License, Version 3.3 (see LICENSE).

                    """
                ),
            )
            assert_header_check(
                added_files=[],
                expected_excerpt="subdir/file.py: header does not match the expected header",
            )

            # Check that a file without a valid copyright year fails.
            safe_file_dump(
                new_py_path,
                dedent(
                    """\
                    # Copyright YYYY Pants project contributors (see CONTRIBUTORS.md).
                    # Licensed under the Apache License, Version 2.0 (see LICENSE).

                    """
                ),
            )
            assert_header_check(
                added_files=[],
                expected_excerpt=(
                    r"subdir/file.py: copyright year must match '20\d\d' (was YYYY): "
                    f"current year is {cur_year}"
                ),
            )

            # Check that a newly added file must have the current year.
            last_year = str(cur_year_num - 1)
            safe_file_dump(
                new_py_path,
                dedent(
                    f"""\
                    # Copyright {last_year} Pants project contributors (see CONTRIBUTORS.md).
                    # Licensed under the Apache License, Version 2.0 (see LICENSE).

                    """
                ),
            )
            rel_new_py_path = os.path.relpath(new_py_path, worktree)
            assert_header_check(
                added_files=[rel_new_py_path],
                expected_excerpt=f"subdir/file.py: copyright year must be {cur_year} (was {last_year})",
            )

            # Check that a file isn't checked against the current year if it is not passed as an
            # arg to the script.
            # Use the same file as last time, with last year's copyright date.
            self._assert_subprocess_success(worktree, [header_check_script, "subdir"])
