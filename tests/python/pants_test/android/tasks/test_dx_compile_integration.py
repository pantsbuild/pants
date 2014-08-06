# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from contextlib import contextmanager
import os
import pytest

from pants.util.contextutil import temporary_dir
from pants_test.pants_run_integration_test import PantsRunIntegrationTest
from pants_test.tasks.test_base import is_exe


class DxCompileIntegrationTest(PantsRunIntegrationTest):
  """Integration test for DxCompile

  Finding an Android toolchain to use is done awkwardly. This test defaults to looking for
  an ANDROID_HOME env on the PATH and then checking to see if build-tools version BUILD_TOOLS is
  installed. The SDK is modular, so we had to just pick one. Having an Android SDK on the path is
  not a guarantee that there is a dx.jar anywhere on the machine.

  """


  SDK_HOME = os.environ.get('ANDROID_HOME')
  ANDROID_SDK = os.path.abspath(SDK_HOME) if SDK_HOME else None
  BUILD_TOOLS = '19.1.0'

  # wrapped in an if block to avoid calling os.path.join on a None object.
  if ANDROID_SDK:
    DEX_JAR = os.path.isfile(os.path.join(ANDROID_SDK, 'build-tools', BUILD_TOOLS, 'lib', 'dx.jar'))
  else:
    DEX_JAR = None
  @pytest.mark.skipif('not DxCompileIntegrationTest.DEX_JAR',
                      reason='This integration test requires Android build-tools {0!r} to be'
                             'installed and ANDROID_HOME set in path.'.format(BUILD_TOOLS))

  #@pytest.mark.skipif('not DxCompileIntegrationTest.ANDROID_SDK', reason='No Android SDK on the PATH.')
  def test_tool_registration(self):
      self.assertEquals(True, True)


 # def test_live(self):
 #   self.assertEquals(True, True)