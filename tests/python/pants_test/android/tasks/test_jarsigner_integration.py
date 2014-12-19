# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
import pytest

from pants_test.android.android_integration_test import AndroidIntegrationTest
from pants_test.tasks.test_base import is_exe


class JarsignerIntegrationTest(AndroidIntegrationTest):
  """Integration test for JarsignerTask.

  The Android SDK is modular, finding an SDK on the PATH is no guarantee that the tools you
  need are anywhere on disk. The TOOLS are the ones needed by the tasks jarsigner depends on.
  If you add a target, you may need to expand the TOOLS list and perhaps define new
  BUILD_TOOLS or TARGET_SDK class variables.
  """

  TOOLS = [
    os.path.join('build-tools', AndroidIntegrationTest.BUILD_TOOLS, 'aapt'),
    os.path.join('build-tools', AndroidIntegrationTest.BUILD_TOOLS, 'lib', 'dx.jar'),
    os.path.join('platforms', 'android-' + AndroidIntegrationTest.TARGET_SDK, 'android.jar')
  ]

  JAVA = is_exe('java')

  tools = AndroidIntegrationTest.requirements(TOOLS) and JAVA

  @pytest.mark.skipif('not JarsignerIntegrationTest.tools',
                      reason='Jarsigner integration test requires the JDK, Android tools {0!r} '
                             'and ANDROID_HOME set in path.'.format(TOOLS))
  def test_jarsigner(self):
    self.jarsigner_test(AndroidIntegrationTest.TEST_TARGET)

  def jarsigner_test(self, target):
    pants_run = self.run_pants(['sign', target])
    self.assert_success(pants_run)
