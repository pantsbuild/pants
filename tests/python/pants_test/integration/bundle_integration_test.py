# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from contextlib import contextmanager

import pytest

from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest
from pants.util.contextutil import temporary_dir


@pytest.mark.skip(reason="times out")
class BundleIntegrationTest(PantsRunIntegrationTest):

    TARGET_PATH = "testprojects/src/java/org/pantsbuild/testproject/bundle"

    def test_bundle_basic(self):
        args = ["-q", "bundle", self.TARGET_PATH]
        self.do_command(*args, success=True)

    @contextmanager
    def bundled(self, target_name):
        with temporary_dir() as temp_distdir:
            with self.pants_results(
                [
                    "-q",
                    f"--pants-distdir={temp_distdir}",
                    "bundle",
                    f"{self.TARGET_PATH}:{target_name}",
                ]
            ) as pants_run:
                self.assert_success(pants_run)
                yield os.path.join(
                    temp_distdir, f"{self.TARGET_PATH.replace('/', '.')}.{target_name}-bundle"
                )

    def test_bundle_mapper(self):
        with self.bundled("mapper") as bundle_dir:
            self.assertTrue(os.path.isfile(os.path.join(bundle_dir, "bundle_files/file1.txt")))

    def test_bundle_relative_to(self):
        with self.bundled("relative_to") as bundle_dir:
            self.assertTrue(os.path.isfile(os.path.join(bundle_dir, "b/file1.txt")))

    def test_bundle_rel_path(self):
        with self.bundled("rel_path") as bundle_dir:
            self.assertTrue(os.path.isfile(os.path.join(bundle_dir, "b/file1.txt")))

    def test_bundle_directory(self):
        with self.bundled("directory") as bundle_dir:
            root = os.path.join(bundle_dir, "a/b")
            self.assertTrue(os.path.isdir(root))
            # NB: The behaviour of this test changed as scheduled in 1.5.0.dev0, because the
            # parent directory is no longer symlinked.
            self.assertFalse(os.path.isfile(os.path.join(root, "file1.txt")))

    def test_bundle_explicit_recursion(self):
        with self.bundled("explicit_recursion") as bundle_dir:
            root = os.path.join(bundle_dir, "a/b")
            self.assertTrue(os.path.isdir(root))
            self.assertTrue(os.path.isfile(os.path.join(root, "file1.txt")))

    def test_bundle_resource_ordering(self):
        """Ensures that `resources=` ordering is respected."""
        pants_run = self.run_pants(
            [
                "-q",
                "run",
                "testprojects/src/java/org/pantsbuild/testproject/bundle:bundle-resource-ordering",
            ]
        )
        self.assert_success(pants_run)
        self.assertEqual(pants_run.stdout_data.strip(), "Hello world from Foo")
