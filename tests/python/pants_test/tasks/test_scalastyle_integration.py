# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest


class ScalastyleIntegrationTest(PantsRunIntegrationTest):

    task_failure_msg = "exited non-zero (1)"
    error_analysis_msg = "Found 2 errors"
    target = "examples/src/scala/org/pantsbuild/example/styleissue"
    config = f"{target}/style.xml"

    def test_scalastyle_without_quiet(self):
        scalastyle_args = [
            f"--scalastyle-config={self.config}",
            "lint.scalastyle",
            self.target,
        ]
        pants_run = self.run_pants(scalastyle_args)
        assert self.task_failure_msg in pants_run.stdout_data
        assert self.error_analysis_msg in pants_run.stdout_data

    def test_scalastyle_with_quiet(self):
        scalastyle_args = [
            f"--scalastyle-config={self.config}",
            "lint.scalastyle",
            "--quiet",
            self.target,
        ]
        pants_run = self.run_pants(scalastyle_args)
        assert self.task_failure_msg in pants_run.stdout_data
        assert self.error_analysis_msg not in pants_run.stdout_data
