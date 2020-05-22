# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import Path

from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest


class FilemapIntegrationTest(PantsRunIntegrationTest):
    PATH_PREFIX = "testprojects/tests/python/pants/file_sets/"
    TEST_EXCLUDE_FILES = {
        "a.py",
        "aa.py",
        "aaa.py",
        "ab.py",
        "aabb.py",
        "test_a.py",
        "dir1/a.py",
        "dir1/aa.py",
        "dir1/aaa.py",
        "dir1/ab.py",
        "dir1/aabb.py",
        "dir1/dirdir1/a.py",
        "dir1/dirdir1/aa.py",
        "dir1/dirdir1/ab.py",
    }

    def setUp(self):
        super().setUp()
        assert self.TEST_EXCLUDE_FILES == {
            str(fp.relative_to(self.PATH_PREFIX))
            for fp in Path(self.PATH_PREFIX).rglob("*.py")
            if not fp.name == "__init__.py"
        }

    def _mk_target(self, test_name):
        return f"{self.PATH_PREFIX}:{test_name}"

    def _extract_exclude_output(self, test_name):
        stdout_data = self.do_command(
            "filemap", self._mk_target(test_name), success=True
        ).stdout_data
        return {
            s.split(" ")[0].replace(self.PATH_PREFIX, "")
            for s in stdout_data.split("\n")
            if s.startswith(self.PATH_PREFIX) and "__init__.py" not in s
        }

    def test_python_sources(self):
        run = self.do_command("filemap", "testprojects/src/python/sources", success=True)
        self.assertIn("testprojects/src/python/sources/sources.py", run.stdout_data)

    def test_exclude_literal_files(self):
        test_out = self._extract_exclude_output("exclude_literal_files")
        self.assertEqual(self.TEST_EXCLUDE_FILES - {"aaa.py", "dir1/aaa.py"}, test_out)

    def test_exclude_globs(self):
        test_out = self._extract_exclude_output("exclude_globs")
        self.assertEqual(self.TEST_EXCLUDE_FILES - {"aabb.py", "dir1/dirdir1/aa.py"}, test_out)

    def test_exclude_recursive_globs(self):
        test_out = self._extract_exclude_output("exclude_recursive_globs")
        self.assertEqual(
            self.TEST_EXCLUDE_FILES
            - {"ab.py", "aabb.py", "dir1/ab.py", "dir1/aabb.py", "dir1/dirdir1/ab.py"},
            test_out,
        )

    def test_implicit_sources(self):
        test_out = self._extract_exclude_output("implicit_sources")
        self.assertEqual({"a.py", "aa.py", "aaa.py", "aabb.py", "ab.py"}, test_out)

        test_out = self._extract_exclude_output("test_with_implicit_sources")
        self.assertEqual({"test_a.py"}, test_out)
