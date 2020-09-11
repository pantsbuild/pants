# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import time

import pytest

from pants.java.jar.manifest import Manifest
from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest
from pants.util.contextutil import open_zip


@pytest.mark.skip(reason="times out")
class ExportClasspathIntegrationTest(PantsRunIntegrationTest):
    def test_export_manifest_jar(self):
        ctimes = []
        manifest_jar_path = "dist/export-classpath/manifest.jar"
        for _ in range(2):
            pants_run = self.run_pants(
                [
                    "export-classpath",
                    "--manifest-jar-only",
                    "examples/src/java/org/pantsbuild/example/hello/simple",
                ]
            )
            self.assert_success(pants_run)
            self.assertTrue(os.path.exists(manifest_jar_path))
            (mode, ino, dev, nlink, uid, gid, size, atime, mtime, ctime) = os.stat(
                manifest_jar_path
            )
            ctimes.append(ctime)
            # ctime is only accurate to second.
            time.sleep(1)

        self.assertTrue(ctimes[1] > ctimes[0], f"{manifest_jar_path} is not overwritten.")

    def test_export_classpath_file_with_excludes(self):
        manifest_jar_path = "dist/export-classpath/manifest.jar"
        pants_run = self.run_pants(
            [
                "export-classpath",
                "--manifest-jar-only",
                "testprojects/src/java/org/pantsbuild/testproject/exclude:foo",
            ]
        )
        self.assert_success(pants_run)
        self.assertTrue(os.path.exists(manifest_jar_path))

        with open_zip(manifest_jar_path) as synthetic_jar:
            self.assertListEqual([Manifest.PATH], synthetic_jar.namelist())
            oneline_classpath = (
                synthetic_jar.read(Manifest.PATH).decode().replace("\n", "").replace(" ", "")
            )
            self.assertNotIn("sbt-interface", oneline_classpath)
            self.assertIn("foo", oneline_classpath)
            self.assertIn("baz", oneline_classpath)
