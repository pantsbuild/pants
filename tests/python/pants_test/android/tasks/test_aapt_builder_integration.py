# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

import pytest

from pants_test.android.android_integration_test import AndroidIntegrationTest


class AaptBuilderIntegrationTest(AndroidIntegrationTest):
  """Integration test for AaptBuilder, which builds an unsigned .apk

  The Android SDK is modular, finding an SDK on the PATH is no guarantee that there is
  an aapt binary anywhere on disk. The TOOLS are the ones required by the target in the
  'test_aapt_bundle' method. If you add a target, you may need to expand the TOOLS list
  and perhaps define new BUILD_TOOLS or TARGET_SDK class variables.
  """

  TOOLS = [
    os.path.join('build-tools', AndroidIntegrationTest.BUILD_TOOLS, 'aapt'),
    os.path.join('build-tools', AndroidIntegrationTest.BUILD_TOOLS, 'lib', 'dx.jar'),
    os.path.join('platforms', 'android-' + AndroidIntegrationTest.TARGET_SDK, 'android.jar')
  ]

  tools = AndroidIntegrationTest.requirements(TOOLS)

  @pytest.mark.skipif('not AaptBuilderIntegrationTest.tools',
                      reason='Android integration test requires tools {0!r} '
                             'and ANDROID_HOME set in path.'.format(TOOLS))
  def test_aapt_bundle(self):
    self.bundle_test(AndroidIntegrationTest.TEST_TARGET)

  def bundle_test(self, target):
    pants_run = self.run_pants(['bundle', target])
    self.assert_success(pants_run)
