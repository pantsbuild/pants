# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
import subprocess

from pants.base.build_environment import get_buildroot
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


# JVM classes can have non-ASCII names. Make sure we don't assume ASCII.


class BundleIntegrationTest(PantsRunIntegrationTest):
  def test_bundle_of_nonascii_classes(self):
    pants_run = self.run_pants(['goal', 'bundle', 'src/java/com/pants/testproject/unicode/main'])
    self.assertEquals(pants_run.returncode, self.PANTS_SUCCESS_CODE,
                      "goal bundle expected success, got {0}\n"
                      "got stderr:\n{1}\n"
                      "got stdout:\n{2}\n".format(pants_run.returncode,
                                                  pants_run.stderr_data,
                                                  pants_run.stdout_data))
    out_path = os.path.join(get_buildroot(), 'dist', 'unicode-bundle')
    java_run = subprocess.Popen(['java', '-jar', 'unicode.jar'],
                                stdout=subprocess.PIPE,
                                cwd=out_path)
    java_retcode = java_run.wait()
    java_out = java_run.stdout.read()
    self.assertEquals(java_retcode, 0)
    self.assertTrue("Have a nice day!" in java_out)
