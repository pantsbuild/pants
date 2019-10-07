# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class ScalastyleIntegrationTest(PantsRunIntegrationTest):

    task_failure_msg = "exited non-zero (1)"
    error_analysis_msg = "Found 2 errors"

    def test_scalastyle_without_quiet(self):
        scalastyle_args = [
            "lint.scalastyle",
            "--config=examples/src/scala/org/pantsbuild/example/styleissue/style.xml",
            "examples/src/scala/org/pantsbuild/example/styleissue",
        ]
        pants_run = self.run_pants(scalastyle_args)
        self.assertIn(self.task_failure_msg, pants_run.stdout_data)
        self.assertIn(self.error_analysis_msg, pants_run.stdout_data)

    def test_scalastyle_with_quiet(self):
        scalastyle_args = [
            "lint.scalastyle",
            "--config=examples/src/scala/org/pantsbuild/example/styleissue/style.xml",
            "--quiet",
            "examples/src/scala/org/pantsbuild/example/styleissue",
        ]
        pants_run = self.run_pants(scalastyle_args)
        self.assertIn(self.task_failure_msg, pants_run.stdout_data)
        self.assertNotIn(self.error_analysis_msg, pants_run.stdout_data)
