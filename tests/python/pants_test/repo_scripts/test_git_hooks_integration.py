# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import subprocess
from contextlib import contextmanager
from pathlib import Path
from textwrap import dedent

from pants.testutil.git_util import create_isolated_git_repo
from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest
from pants.util.contextutil import pushd
from pants.util.dirutil import chmod_plus_x, safe_file_dump


class PreCommitHookIntegrationTest(PantsRunIntegrationTest):

    _lint_files_to_format_script = Path("build-support/bin/lint_providing_files_to_format.sh")

    _test_library_file = Path("src/python/python_targets/test_library.py")

    @contextmanager
    def _isolated_pants_git_repo(self):
        with create_isolated_git_repo(to_copy=["build-support", "pants.pex"]) as worktree, pushd(
            worktree
        ):
            chmod_plus_x("pants.pex")
            os.symlink("pants.pex", "pants")
            yield worktree

    def test_lint_would_reformat_files(self):
        with self._isolated_pants_git_repo():
            safe_file_dump(
                self._test_library_file,
                dedent(
                    """\
            x = '3'
            """
                ),
            )
            result = subprocess.run(
                [str(self._lint_files_to_format_script), "HEAD"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            assert result.returncode != 0
            assert f"would reformat {self._test_library_file}" in result.stderr.decode()
