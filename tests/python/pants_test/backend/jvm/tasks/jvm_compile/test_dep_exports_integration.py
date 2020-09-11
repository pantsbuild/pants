# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import re
import shutil

import pytest

from pants.base.build_environment import get_buildroot
from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest


@pytest.mark.skip(reason="takes too long")
class DepExportsIntegrationTest(PantsRunIntegrationTest):

    SRC_PREFIX = "testprojects/tests"
    SRC_TYPES = ["java", "scala"]
    SRC_PACKAGE = "org/pantsbuild/testproject/exports"

    @classmethod
    def hermetic(cls):
        return True

    def modify_exports_and_compile(self, target, modify_file):
        with self.temporary_sourcedir() as tmp_src:
            src_dir = os.path.relpath(
                os.path.join(tmp_src, os.path.basename(self.SRC_PACKAGE)), get_buildroot()
            )
            target_dir, target_name = target.rsplit(":", 1)
            shutil.copytree(target_dir, src_dir)
            with self.temporary_workdir() as workdir:
                cmd = [
                    "compile",
                    "--source-root-patterns=tests/*",
                    "--scalafmt-skip",
                    f"{src_dir}:{target_name}",
                ]
                pants_run = self.run_pants_with_workdir(command=cmd, workdir=workdir)
                self.assert_success(pants_run)

                with open(os.path.join(src_dir, modify_file), "a") as fh:
                    fh.write("\n")

                pants_run = self.run_pants_with_workdir(command=cmd, workdir=workdir)
                self.assert_success(pants_run)
                self.assertTrue(f"{src_dir}:{target_name}" in pants_run.stdout_data)

    def test_invalidation(self):
        for lang in self.SRC_TYPES:
            path = os.path.join(self.SRC_PREFIX, lang, self.SRC_PACKAGE)
            target = f"{path}:D"
            self.modify_exports_and_compile(target, f"A.{lang}")
            self.modify_exports_and_compile(target, f"B.{lang}")

    def test_non_exports(self):
        pants_run = self.run_pants(
            [
                "compile",
                "--source-root-patterns=tests/scala",
                "--scalafmt-skip",
                "testprojects/tests/scala/org/pantsbuild/testproject/non_exports:C",
            ]
        )
        self.assert_failure(pants_run)
        self.assertTrue(
            re.search(
                "Compilation failure.*testprojects/tests/scala/org/pantsbuild/testproject/non_exports:C",
                pants_run.stdout_data,
            )
        )


class DepExportsThriftTargets(PantsRunIntegrationTest):
    def test_exports_for_thrift_targets(self):
        pants_run = self.run_pants(
            ["compile", "testprojects/src/thrift/org/pantsbuild/thrift_exports:C-with-exports"]
        )
        self.assert_success(pants_run)

        pants_run = self.run_pants(
            ["compile", "testprojects/src/thrift/org/pantsbuild/thrift_exports:C-without-exports"]
        )
        self.assert_failure(pants_run)
        self.assertIn(
            "Symbol 'type org.pantsbuild.thrift_exports.thriftscala.FooA' is missing from the classpath",
            pants_run.stdout_data,
        )
