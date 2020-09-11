# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import re

import pytest

from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest
from pants.util.dirutil import read_file

TEST_DIR = "testprojects/src/scala/org/pantsbuild/testproject"


@pytest.mark.skip(reason="times out")
class ScalaFixIntegrationTest(PantsRunIntegrationTest):
    @classmethod
    def hermetic(cls):
        return True

    def test_scalafix_fail(self):

        rules = {"rules": "ProcedureSyntax"}
        options = {"lint.scalafix": rules, "fmt.scalafix": rules, "scalastyle": {"skip": True}}

        target = f"{TEST_DIR}/procedure_syntax"
        # lint should fail because the rule has an impact.
        failing_test = self.run_pants(["lint", target], options)
        self.assert_failure(failing_test)

    def test_scalafix_disabled(self):

        rules = {"rules": "ProcedureSyntax"}
        options = {"lint.scalafix": rules, "fmt.scalafix": rules, "scalastyle": {"skip": True}}

        # take a snapshot of the file which we can write out
        # after the test finishes executing.
        test_file_name = f"{TEST_DIR}/procedure_syntax/ProcedureSyntax.scala"

        with self.with_overwritten_file_content(test_file_name):
            # format an incorrectly formatted file.
            target = f"{TEST_DIR}/procedure_syntax"
            fmt_result = self.run_pants(["fmt", target], options)
            self.assert_success(fmt_result)

            # verify that the lint check passes.
            test_fix = self.run_pants(["lint", target], options)
            self.assert_success(test_fix)

    def test_scalafix_scalacoptions(self):

        rules = {"rules": "RemoveUnused", "semantic": True}
        options = {
            "source": {"root_patterns": ["src/*", "tests/*"]},
            "scala": {
                "scalac_plugin_dep": f"{TEST_DIR}/rsc_compat:semanticdb-scalac",
                "scalac_plugins": '+["semanticdb"]',
            },
            "compile.rsc": {"args": '+["-S-Ywarn-unused"]'},
            "lint.scalafix": rules,
            "fmt.scalafix": rules,
            "scalastyle": {"skip": True},
        }

        test_file_name = f"{TEST_DIR}/rsc_compat/RscCompat.scala"

        with self.with_overwritten_file_content(test_file_name):
            # format an incorrectly formatted file.
            target = f"{TEST_DIR}/rsc_compat"
            fmt_result = self.run_pants(["fmt", target], options)
            self.assert_success(fmt_result)

            # verify that the lint check passes.
            test_fix = self.run_pants(["lint", target], options)
            self.assert_success(test_fix)

    def test_rsccompat_fmt(self):
        options = {
            "scala": {
                "scalac_plugin_dep": f"{TEST_DIR}/rsc_compat:semanticdb-scalac",
                "scalac_plugins": '+["semanticdb"]',
            },
            "fmt.scalafix": {
                "rules": "scala:rsc.rules.RscCompat",
                "semantic": True,
                "scalafix_tool_classpath": f"{TEST_DIR}/rsc_compat:rsc-compat",
            },
        }

        test_file_name = f"{TEST_DIR}/rsc_compat/RscCompat.scala"
        fixed_file_name = f"{TEST_DIR}/rsc_compat/RscCompatFixed.scala"

        with self.with_overwritten_file_content(test_file_name):
            # format an incorrectly formatted file.
            target = f"{TEST_DIR}/rsc_compat"
            fmt_result = self.run_pants(["fmt", target], options)
            self.assert_success(fmt_result)

            result = read_file(test_file_name)
            result = re.sub(re.escape("object RscCompat {"), "object RscCompatFixed {", result)
            expected = read_file(fixed_file_name)
            self.assertEqual(result, expected)
