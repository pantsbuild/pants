# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import subprocess

from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest
from pants.util.dirutil import safe_delete


class GoBinaryIntegrationTest(PantsRunIntegrationTest):
    def test_go_crosscompile(self):
        # We assume that targeting windows is cross-compiling.
        output_file = "dist/go/bin/hello.exe"
        safe_delete(output_file)
        args = ["binary", "contrib/go/examples/src/go/hello"]
        pants_run = self.run_pants(args, extra_env={"GOOS": "windows"})
        self.assert_success(pants_run)
        self.assertIn(b"for MS Windows", subprocess.check_output(["file", output_file]))
