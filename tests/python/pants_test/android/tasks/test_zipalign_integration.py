# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

import pytest

from pants_test.android.android_integration_test import AndroidIntegrationTest


class ZipalignIntegrationTest(AndroidIntegrationTest):
  """Integration test for SignApkTask.

  The Android SDK is modular, finding an SDK on the PATH is no guarantee that the tools you
  need are anywhere on disk. The TOOLS are the ones needed by the tasks SignApk depends on.
  If you add a target, you may need to expand the TOOLS list and perhaps define new
  BUILD_TOOLS or TARGET_SDK class variables.
  """

  TOOLS = [
    os.path.join('build-tools', AndroidIntegrationTest.BUILD_TOOLS, 'aapt'),
    os.path.join('build-tools', AndroidIntegrationTest.BUILD_TOOLS, 'zipalign'),
    os.path.join('build-tools', AndroidIntegrationTest.BUILD_TOOLS, 'lib', 'dx.jar'),
    os.path.join('platforms', 'android-' + AndroidIntegrationTest.TARGET_SDK, 'android.jar')
  ]

  requirements = AndroidIntegrationTest.requirements(TOOLS)

  @pytest.mark.skipif('not ZipalignIntegrationTest.requirements',
                      reason='Zipalign integration test requires the JDK, Android tools {0!r} '
                             'and ANDROID_HOME set in path.'.format(TOOLS))
  def test_zipalign(self):
    self.zipalign_test(AndroidIntegrationTest.TEST_TARGET)

  def zipalign_test(self, target):
    pants_run = self.run_pants(['binary', target])
    self.assert_success(pants_run)
