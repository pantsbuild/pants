# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
import pytest

from pants.base.build_environment import get_buildroot
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class DxCompileIntegrationTest(PantsRunIntegrationTest):
  """Integration test for DxCompile

  Finding an Android toolchain to use is done awkwardly. This test defaults to looking for
  an ANDROID_HOME env on the PATH and then checking to see if build-tools version BUILD_TOOLS is
  installed. The SDK is modular, so we had to just pick one. Having an Android SDK on the path is
  not a guarantee that there is a dx.jar anywhere on the machine.

  """

  BUILD_TOOLS = '19.1.0'
  DEX_FILE = 'classes.dex'
  TARGET_SDK = '19'
  SDK_HOME = os.environ.get('ANDROID_HOME')
  ANDROID_SDK = os.path.abspath(SDK_HOME) if SDK_HOME else None


  # wrapped in an if block to avoid calling os.path.join on a None object.
  @classmethod
  def requirements(cls):
    if cls.ANDROID_SDK:
      if os.path.isfile(os.path.join(cls.ANDROID_SDK, 'build-tools', cls.BUILD_TOOLS, 'lib', 'dx.jar')):
        if os.path.isfile(os.path.join(cls.ANDROID_SDK, 'platforms', 'android-' + cls.TARGET_SDK, 'android.jar')):
          return True
    return False

  @pytest.mark.skipif('not DxCompileIntegrationTest.requirements()',
                      reason='This integration test requires Android build-tools {0!r} to be'
                             'installed and ANDROID_HOME set in path.'.format(BUILD_TOOLS))

  def test_dx_compile(self):
    self.publish_test('src/android/example:hello')

  def publish_test(self, target):
      pants_run = self.run_pants(['goal', 'dex', target] )
      self.assertEquals(pants_run.returncode, self.PANTS_SUCCESS_CODE,
                        "goal publish expected success, got {0}\n"
                        "got stderr:\n{1}\n"
                        "got stdout:\n{2}\n".format(pants_run.returncode,
                                                    pants_run.stderr_data,
                                                    pants_run.stdout_data))
