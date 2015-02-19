# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from contextlib import contextmanager

import pytest

from pants.backend.android.distribution.android_distribution import AndroidDistribution
from pants.util.contextutil import environment_as
from pants_test.android.test_android_base import TestAndroidBase


class TestAndroidDistribution(TestAndroidBase):

  def test_tool_registration(self):
    with self.distribution() as sdk:
      AndroidDistribution(sdk_path=sdk).register_android_tool(
              os.path.join(sdk, 'build-tools', '19.1.0', 'aapt'))

    with self.distribution() as sdk:
      AndroidDistribution(sdk_path=sdk).register_android_tool(
        os.path.join(sdk, 'platforms', 'android-19', 'android.jar'))

    with pytest.raises(AndroidDistribution.Error):
      AndroidDistribution(sdk_path=sdk).register_android_tool(
        os.path.join(sdk, 'build-tools', 'bad-number', 'aapt'))

    with pytest.raises(AndroidDistribution.Error):
      AndroidDistribution(sdk_path=sdk).register_android_tool(
        os.path.join(sdk, 'platforms', 'not-a-platform', 'android.jar'))


  def test_locate_sdk_path(self, path=None):
    # We can set good/bad paths alike. No checks until tools are called.

    @contextmanager
    def env(**kwargs):
      environment = dict(ANDROID_HOME=None, ANDROID_SDK_HOME=None, ANDROID_SDK=None)
      environment.update(**kwargs)
      with environment_as(**environment):
        yield

    with self.distribution() as sdk:
      with env(ANDROooooD_HOME=sdk):
        AndroidDistribution.locate_sdk_path(path)

    with self.distribution() as sdk:
      with env(ANDROID_HOME=sdk):
        AndroidDistribution.locate_sdk_path(path)

# No live test for now, the varying installed platforms make that unpredictable.
