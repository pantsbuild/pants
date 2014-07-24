# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from contextlib import contextmanager
import os
import pytest
import unittest2

from twitter.common.collections import maybe_list

from pants.backend.android.distribution.android_distribution import AndroidDistribution
from pants.util.contextutil import environment_as, temporary_dir
from pants.util.dirutil import chmod_plus_x, safe_open, touch


class TestAndroidDistributionTest(unittest2.TestCase):

  @contextmanager
  # default for testing purposes being sdk 18 and 19, with latest build-tools 19.1.0
  def distribution(self, installed_sdks=('18', '19'),
                   installed_build_tools=('19.1.0', ),
                   files='android.jar',
                   executables='aapt'):
    with temporary_dir() as sdk:
      for sdks in installed_sdks:
        touch(os.path.join(sdk, 'platforms', 'android-' + sdks, files))
      for build in installed_build_tools:
        for exe in maybe_list(executables or ()):
          path = os.path.join(sdk, 'build-tools', build, exe)
          with safe_open(path, 'w') as fp:
            fp.write('')
          chmod_plus_x(path)
      yield sdk

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
