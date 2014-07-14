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
from twitter.common.contextutil import environment_as, temporary_dir
from twitter.common.dirutil import chmod_plus_x, safe_mkdir, safe_open, touch

from pants.backend.android.distribution.android_distribution import AndroidDistribution


class TestAndroidDistributionTest(unittest2.TestCase):

  @contextmanager
  # default for testing purposes being sdk 18 and 19, with latest build-tools 19.1.0
  def distribution(self, installed_sdks=["18", "19"],
                   installed_build_tools=["19.1.0"],
                   files='android.jar',
                   executables='aapt'):
    with temporary_dir() as sdk:
      for sdks in installed_sdks:
        test_aapt = touch(os.path.join(sdk, 'platforms', 'android-' + sdks, files))
      for build in installed_build_tools:
        for exe in maybe_list(executables or ()):
          path = os.path.join(sdk, 'build-tools', build, exe)
          with safe_open(path, 'w') as fp:
            fp.write('')
          chmod_plus_x(path)
      yield sdk

  def test_tool_retrieval(self):
    with self.distribution() as sdk:
      AndroidDistribution(sdk_path=sdk).aapt_tool('19.1.0')

    with self.distribution() as sdk:
      AndroidDistribution(sdk_path=sdk).android_jar_tool('18')

    with pytest.raises(AndroidDistribution.Error):
      with self.distribution() as sdk:
        AndroidDistribution(sdk_path=sdk).aapt_tool('99.9.9')

    with pytest.raises(AndroidDistribution.Error):
      with self.distribution() as sdk:
        AndroidDistribution(sdk_path=sdk).android_jar_tool('99')


  def test_set_sdk_path(self, path=None):
    # We can set good/bad paths alike. No checks until tools are called.

    @contextmanager
    def env(**kwargs):
      environment = dict(ANDROID_HOME=None, ANDROID_SDK_HOME=None, ANDROID_SDK=None)
      environment.update(**kwargs)
      with environment_as(**environment):
        yield

    with self.distribution() as sdk:
      with env(ANDROooooD_HOME=sdk):
        AndroidDistribution.set_sdk_path(path)

    with self.distribution() as sdk:
      with env(ANDROID_HOME=sdk):
        AndroidDistribution.set_sdk_path(path)


# No live test for now, the varying installed platforms make that unpredictable.