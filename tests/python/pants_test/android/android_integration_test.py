# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class AndroidIntegrationTest(PantsRunIntegrationTest):
  """Ensure a base SDK to run any Android integration tests.

  The Android SDK is modular, finding an SDK on the PATH is no guarantee that there is
  a dx.jar anywhere on disk. In this test we look for a set of default tools that will get the
  job done or the test is skipped. The TARGET_SDK version must match the targetSDK value in the
  AndroidManifest.xml of the target while the BUILD_TOOLS version is arbitrary.
  """
  BUILD_TOOLS = '19.1.0'
  TARGET_SDK = '19'
  ANDROID_SDK_LOCATION = 'ANDROID_HOME'

  @classmethod
  def requirements(cls, tools):
    sdk_home = os.environ.get('ANDROID_HOME')
    android_sdk = os.path.abspath(sdk_home) if sdk_home else None
    if android_sdk:
      for tool in tools:
        if not os.path.isfile(os.path.join(android_sdk, tool)):
          return False
    return True

