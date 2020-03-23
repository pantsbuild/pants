# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest


class GoRunIntegrationTest(PantsRunIntegrationTest):
    def test_go_run_simple(self):
        args = ["run", "contrib/go/examples/src/go/hello", "--", "-n=3"]
        pants_run = self.run_pants(args)
        self.assert_success(pants_run)

    def test_go_run_cgo(self):
        args = ["-q", "run", "contrib/go/examples/src/go/cgo"]
        pants_run = self.run_pants(args)
        self.assert_success(pants_run)
        self.assertRegex(pants_run.stdout_data.strip(), r"^Random from C: \d+$")
