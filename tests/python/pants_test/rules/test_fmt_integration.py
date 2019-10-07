# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class FmtIntegrationTest(PantsRunIntegrationTest):
    def test_fmt_for_unsupported_target_should_noop(self):
        command = ["fmt-v2", "testprojects/tests/java/org/pantsbuild/testproject/dummies/::"]
        pants_run = self.run_pants(command=command)
        self.assert_success(pants_run)
        self.assertNotIn("reformatted", pants_run.stderr_data)
        self.assertNotIn("unchanged", pants_run.stderr_data)
