# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
import pytest

from pants_test.android.android_integration_test import AndroidIntegrationTest


class DxCompileIntegrationTest(AndroidIntegrationTest):
  """Integration test for DxCompile

  The Android SDK is modular, finding an SDK on the PATH is no guarantee that there is
  a dx.jar anywhere on disk. In this test we look for a set of default tools that will get the
  job done or the test is skipped. The TARGET_SDK version must match the targetSDK value in the
  AndroidManifest.xml of the target while the BUILD_TOOLS version is arbitrary.
  """
  TOOLS = [
    os.path.join('build-tools', AndroidIntegrationTest.BUILD_TOOLS, 'lib', 'dx.jar'),
    os.path.join('platforms', 'android-' + AndroidIntegrationTest.TARGET_SDK, 'android.jar')
  ]

  reqs = AndroidIntegrationTest.requirements(TOOLS)

  @pytest.mark.skipif('not DxCompileIntegrationTest.reqs',
                      reason='Android integration test requires tools {0!r} '
                             'and ANDROID_HOME set in path.'.format(TOOLS))
  def test_dx_compile(self):
    self.dx_test('src/android/example:hello')

  def dx_test(self, target):
      pants_run = self.run_pants(['goal', 'dex', target])
      self.assertEquals(pants_run.returncode, self.PANTS_SUCCESS_CODE,
                        "goal publish expected success, got {0}\n"
                        "got stderr:\n{1}\n"
                        "got stdout:\n{2}\n".format(pants_run.returncode,
                                                    pants_run.stderr_data,
                                                    pants_run.stdout_data))

  #TODO(mateor): if in the future DxCompile outputs to dist then we can verify the artifact here.