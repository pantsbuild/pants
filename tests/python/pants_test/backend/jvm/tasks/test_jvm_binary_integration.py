# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import subprocess

from pants.base.build_environment import get_buildroot
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class JvmBinaryIntegrationTest(PantsRunIntegrationTest):

  def test_manifest_entries(self):
    self.assert_success(self.run_pants(['clean-all']))
    args = ['binary', 'testprojects/src/java/org/pantsbuild/testproject/manifest']
    pants_run = self.run_pants(args, {})
    self.assert_success(pants_run)

    out_path = os.path.join(get_buildroot(), 'dist')
    java_run = subprocess.Popen(['java', '-cp', 'manifest.jar',
                                 'org.pantsbuild.testproject.manifest.Manifest'],
                                stdout=subprocess.PIPE,
                                cwd=out_path)
    java_retcode = java_run.wait()
    java_out = java_run.stdout.read()
    self.assertEquals(java_retcode, 0)
    self.assertIn('Hello World!  Version: 1.2.3', java_out)
