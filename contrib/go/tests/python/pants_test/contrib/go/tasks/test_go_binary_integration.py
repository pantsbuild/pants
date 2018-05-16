# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.util.dirutil import safe_delete
from pants.util.process_handler import subprocess
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class GoBinaryIntegrationTest(PantsRunIntegrationTest):

  def test_go_crosscompile(self):
    # We assume that targeting windows is cross-compiling.
    output_file = "dist/go/bin/hello.exe"
    safe_delete(output_file)
    args = ['binary',
            'contrib/go/examples/src/go/hello']
    pants_run = self.run_pants(args, extra_env={"GOOS": "windows"})
    self.assert_success(pants_run)
    self.assertIn("for MS Windows", subprocess.check_output(["file", output_file]))
