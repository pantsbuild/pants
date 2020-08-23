# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.testutil.pants_integration_test import PantsIntegrationTest


class BuildIgnoreIntegrationTest(PantsIntegrationTest):
    def test_build_ignore_list(self):
        with self.setup_tmpdir({"dir/BUILD": "files(sources=[])"}) as tmpdir:
            ignore_result = self.run_pants(
                [f"--build-ignore={tmpdir}/dir", "list", f"{tmpdir}/dir"]
            )
            no_ignore_result = self.run_pants(["list", f"{tmpdir}/dir"])
        self.assert_failure(ignore_result)
        assert f"{tmpdir}/dir" in ignore_result.stderr
        self.assert_success(no_ignore_result)
        assert f"{tmpdir}/dir" in no_ignore_result.stdout

    def test_build_ignore_dependency(self) -> None:
        sources = {
            "dir1/BUILD": "files(sources=[])",
            "dir2/BUILD": "files(sources=[], dependencies=['{tmpdir}/dir1'])",
        }
        with self.setup_tmpdir(sources) as tmpdir:
            ignore_result = self.run_pants(
                [f"--build-ignore={tmpdir}/dir1", "dependencies", f"{tmpdir}/dir2"]
            )
            no_ignore_result = self.run_pants(["dependencies", f"{tmpdir}/dir2"])
        self.assert_failure(ignore_result)
        assert f"{tmpdir}/dir1" in ignore_result.stderr
        self.assert_success(no_ignore_result)
        assert f"{tmpdir}/dir1" in no_ignore_result.stdout
