# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import Path

from pants.base.build_environment import get_buildroot
from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest
from pants.util.contextutil import temporary_dir


class BuildIgnoreIntegrationTest(PantsRunIntegrationTest):
    """Tests the functionality of the `build_ignore_patterns` option."""

    def test_build_ignore_list(self):
        with temporary_dir(root_dir=get_buildroot()) as tmpdir:
            tmpdir_relative = Path(tmpdir).relative_to(get_buildroot())
            Path(tmpdir, "dir").mkdir()
            Path(tmpdir, "dir", "BUILD").write_text("files(sources=[])")
            ignore_result = self.run_pants(
                [f"--build-ignore={tmpdir_relative}/dir", "list", f"{tmpdir_relative}/dir"]
            )
            no_ignore_result = self.run_pants(["list", f"{tmpdir_relative}/dir"])
        self.assert_failure(ignore_result)
        assert f"{tmpdir_relative}/dir" in ignore_result.stderr_data
        self.assert_success(no_ignore_result)
        assert f"{tmpdir_relative}/dir:dir" in no_ignore_result.stdout_data

    def test_build_ignore_dependency(self) -> None:
        with temporary_dir(root_dir=get_buildroot()) as tmpdir:
            tmpdir_relative = Path(tmpdir).relative_to(get_buildroot())
            Path(tmpdir, "dir1").mkdir()
            Path(tmpdir, "dir1", "BUILD").write_text("files(sources=[])")
            Path(tmpdir, "dir2").mkdir()
            Path(tmpdir, "dir2", "BUILD").write_text(
                f"files(sources=[], dependencies=['{tmpdir_relative}/dir1'])"
            )
            ignore_result = self.run_pants(
                [f"--build-ignore={tmpdir_relative}/dir1", "dependencies", f"{tmpdir_relative}/dir2"]
            )
            no_ignore_result = self.run_pants(["dependencies", f"{tmpdir_relative}/dir2"])
        self.assert_failure(ignore_result)
        assert f"{tmpdir_relative}/dir1" in ignore_result.stderr_data
        self.assert_success(no_ignore_result)
        assert f"{tmpdir_relative}/dir1" in no_ignore_result.stdout_data
