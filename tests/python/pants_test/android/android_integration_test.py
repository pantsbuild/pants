# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.java.distribution.distribution import Distribution, DistributionLocator
from pants_test.pants_run_integration_test import PantsRunIntegrationTest
from pants_test.subsystem.subsystem_util import subsystem_instance


class AndroidIntegrationTest(PantsRunIntegrationTest):
  """Ensure a base SDK to run any Android integration tests.

  The Android SDK is modular, finding an SDK on the PATH is no guarantee that any certain
  tool is on disk. For integration tests we define a set of default tools and
  if they cannot be found the integration test is skipped.
  """
  BUILD_TOOLS = '19.1.0'
  TARGET_SDK = '19'
  ANDROID_SDK_LOCATION = 'ANDROID_HOME'

  JAVA_MIN = '1.6.0_00'
  JAVA_MAX = '1.7.0_99'
  TEST_TARGET = 'examples/src/android/hello'

  @classmethod
  def requirements(cls, tools):
    sdk_home = os.environ.get('ANDROID_HOME')
    android_sdk = os.path.abspath(sdk_home) if sdk_home else None
    if android_sdk:
      for tool in tools:
        if not os.path.isfile(os.path.join(android_sdk, tool)):
          return False
    else:
      return False
    try:
      with subsystem_instance(DistributionLocator) as locator:
        locator.cached(minimum_version=cls.JAVA_MIN, maximum_version=cls.JAVA_MAX)
    except Distribution.Error:
      return False
    return True
