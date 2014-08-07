# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
import pytest

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class DxCompileIntegrationTest(PantsRunIntegrationTest):
  """Integration test for DxCompile

  The Android SDK is modular, finding an SDK on the PATH is no guarantee that there is
  a dx.jar anywhere on disk. In this test we look for a set of default tools that will get the
  job done or the test is skipped. The TARGET_SDK version must match the targetSDK value in the
  AndroidManifest.xml of the target while the BUILD_TOOLS version is arbitrary.
  """
  BUILD_TOOLS = '19.1.0'
  TARGET_SDK = '19'
  ANDROID_SDK_LOCATION = 'ANDROID_HOME'
  DEX_FILE = 'classes.dex'

  @classmethod
  def requirements(cls):
    sdk_home = os.environ.get('ANDROID_HOME')
    android_sdk = os.path.abspath(sdk_home) if sdk_home else None
    if android_sdk:
      if os.path.isfile(os.path.join(android_sdk, 'build-tools', cls.BUILD_TOOLS, 'lib',
                                     'dx.jar')):
        if os.path.isfile(os.path.join(android_sdk, 'platforms', 'android-' + cls.TARGET_SDK,
                                       'android.jar')):
          return True
    return False

  @pytest.mark.skipif('not DxCompileIntegrationTest.requirements()',
                      reason='Dx integration test requires Android build-tools {0!r}, SDK {1!r}'
                             ' and ANDROID_HOME set in path.'.format(BUILD_TOOLS, TARGET_SDK))
  def test_dx_compile(self):
    self.publish_test('src/android/example:hello')

  def publish_test(self, target):
      pants_run = self.run_pants(['goal', 'dex', target])
      self.assertEquals(pants_run.returncode, self.PANTS_SUCCESS_CODE,
                        "goal publish expected success, got {0}\n"
                        "got stderr:\n{1}\n"
                        "got stdout:\n{2}\n".format(pants_run.returncode,
                                                    pants_run.stderr_data,
                                                    pants_run.stdout_data))

  #TODO(mateor): if in the future DxCompile outputs to dist then we can verify the artifact here.