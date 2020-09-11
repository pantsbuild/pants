# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import Path
from textwrap import dedent

import pytest

from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest


@pytest.mark.skip(reason="times out")
class TestJvmAppIntegrationTest(PantsRunIntegrationTest):

    BUNDLE_DIRECTORY = "testprojects/src/java/org/pantsbuild/testproject/bundle"

    def test_bundle(self):
        """Default bundle with --no-deployjar.

        Verify synthetic jar contains only a manifest file and the rest bundle contains other
        library jars.
        """
        self.assertEqual(
            "Hello world from Foo\n",
            self.bundle_and_run(
                self.BUNDLE_DIRECTORY,
                "testprojects.src.java.org.pantsbuild.testproject.bundle.bundle",
                bundle_jar_name="bundle-example-bin",
                # this is the only thing bundle jar has, which means Class-Path must be properly
                # set for its Manifest.
                expected_bundle_jar_content=["META-INF/MANIFEST.MF"],
                expected_bundle_content=[
                    "bundle-example-bin.jar",
                    "data/exampledata.txt",
                    "libs/3rdparty.guava-0.jar",
                    "libs/testprojects.src.java.org.pantsbuild.testproject.bundle.bundle-bin-0.jar",
                    "libs/testprojects.src.resources.org.pantsbuild.testproject.bundleresources.resources-0.jar",
                ],
            ),
        )

    def test_bundle_deployjar(self):
        """bundle with --deployjar.

        Verify monolithic jar is created with manifest file and the library class.
        """
        self.assertEqual(
            "Hello world from Foo\n",
            self.bundle_and_run(
                self.BUNDLE_DIRECTORY,
                "testprojects.src.java.org.pantsbuild.testproject.bundle.bundle",
                bundle_jar_name="bundle-example-bin",
                bundle_options=["--deployjar"],
                # this is the only thing bundle zip has, all class files must be there.
                expected_bundle_content=["bundle-example-bin.jar", "data/exampledata.txt"],
            ),
        )

    def test_missing_files(self):
        build_path = Path(self.BUNDLE_DIRECTORY, "BUILD")
        original_content = build_path.read_text()
        new_content = dedent(
            """\
            jvm_app(
              name='missing-files',
              basename = 'bundle-example',
              binary=':bundle-bin',
              bundles=[
                bundle(fileset=['data/no-such-file']),
              ]
            )
            """
        )
        with self.with_overwritten_file_content(
            str(build_path), f"{original_content}\n{new_content}"
        ):
            pants_run = self.run_pants(["bundle", f"{self.BUNDLE_DIRECTORY}:missing-files"])
        self.assert_failure(pants_run)
