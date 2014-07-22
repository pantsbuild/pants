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
from pants.util.dirutil import chmod_plus_x, safe_open, touch

from pants.backend.android.distribution.android_distribution import AndroidDistribution


class TestAndroidDistributionTest(unittest2.TestCase):

  @contextmanager
  # default for testing purposes being sdk 18 and 19, with latest build-tools 19.1.0
  def distribution(self, installed_sdks=('18', '19'),
                   installed_build_tools=('19.1.0', ),
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

  def test_validate(self):
    with pytest.raises(TypeError):
      with self.distribution() as sdk:
        AndroidDistribution(sdk_path=sdk).validate(target_sdk='19')

    with pytest.raises(TypeError):
      with self.distribution() as sdk:
        AndroidDistribution(sdk_path=sdk).validate(build_tools_version='19.1.0')

    with pytest.raises(TypeError):
      with self.distribution() as sdk:
        AndroidDistribution(sdk_path=sdk).validate(sdk_path="18", build_tools_version="1.1.1")

    with pytest.raises(AndroidDistribution.Error):
      with self.distribution() as sdk:
        AndroidDistribution(sdk_path=sdk).validate(target_sdk="9999", build_tools_version="19.1.0")

    with pytest.raises(AndroidDistribution.Error):
      with self.distribution() as sdk:
        AndroidDistribution(sdk_path=sdk).validate(target_sdk="18", build_tools_version="999.1.0")

    with self.distribution() as sdk:
      AndroidDistribution(sdk_path=sdk).validate(target_sdk="18", build_tools_version="19.1.0")

  def test_locate_tools(self):
    with self.distribution() as sdk:
      self.assertEquals(False, AndroidDistribution(sdk_path=sdk)
                        .locate_build_tools(build_tools_version="20"))

    with self.distribution() as sdk:
      self.assertEquals(False, AndroidDistribution(sdk_path=sdk)
                        .locate_build_tools(build_tools_version=""))

    with pytest.raises(TypeError):
      with self.distribution() as sdk:
        AndroidDistribution(sdk_path=sdk).locate_build_tools(target_sdk="19.1.0")

    with self.distribution() as sdk:
      self.assertEquals(True, AndroidDistribution(sdk_path=sdk)
                        .locate_build_tools(build_tools_version="19.1.0"))

  def test_locate_sdk(self):
    with self.distribution() as sdk:
      self.assertEquals(False, AndroidDistribution(sdk_path=sdk).locate_target_sdk(target_sdk="22"))

    with self.distribution() as sdk:
      self.assertEquals(False, AndroidDistribution(sdk_path=sdk).locate_target_sdk(target_sdk="1"))

    with self.distribution() as sdk:
      self.assertEquals(False, AndroidDistribution(sdk_path=sdk).locate_target_sdk(target_sdk=""))

    with self.distribution() as sdk:
      self.assertEquals(True, AndroidDistribution(sdk_path=sdk).locate_target_sdk(target_sdk="18"))


  def test_tools(self):
    with self.distribution() as sdk:
      self.assertEquals(os.path.join(sdk, 'build-tools', '19.1.0', 'aapt'),
                        AndroidDistribution(sdk_path=sdk).aapt_tool('19.1.0'))

    with self.distribution() as sdk:
      self.assertEquals(os.path.join(sdk, 'platforms', 'android-18', 'android.jar'),
                        AndroidDistribution(sdk_path=sdk).android_jar_tool('18'))

    with pytest.raises(AssertionError):
      with self.distribution() as sdk:
        self.assertEquals(os.path.join(sdk, 'build-tools', '19.1.0', 'aapt'),
                        AndroidDistribution(sdk_path=sdk).aapt_tool('99.9.9'))

    with pytest.raises(AssertionError):
      with self.distribution() as sdk:
        self.assertEquals(os.path.join(sdk, 'platforms', 'android-18', 'android.jar'),
                          AndroidDistribution(sdk_path=sdk).android_jar_tool('99'))

  def test_locate(self):
    @contextmanager
    def env(**kwargs):
      environment = dict(ANDROID_HOME=None, ANDROID_SDK_HOME=None, ANDROID_SDK=None)
      environment.update(**kwargs)
      with environment_as(**environment):
        yield

    with pytest.raises(AndroidDistribution.Error):
      with env():
        AndroidDistribution.locate()

    with pytest.raises(AndroidDistribution.Error):
      with self.distribution(files='android.jar') as sdk:
        with env(PATH=sdk):
          AndroidDistribution.locate()

    with pytest.raises(AndroidDistribution.Error):
      with self.distribution() as sdk:
        with env(PATH=sdk):
          AndroidDistribution.locate(target_sdk='99')
      with self.distribution() as sdk:
        with env(PATH=sdk):
          AndroidDistribution.locate(build_tools_version='99.1.0')

    with pytest.raises(AndroidDistribution.Error):
      with self.distribution() as sdk:
        with env(ANDROooooD_HOME=sdk):
          AndroidDistribution.locate()

    with self.distribution() as sdk:
      with env(ANDROID_HOME=sdk):
        AndroidDistribution.locate()

    with self.distribution() as sdk:
      with env(ANDROID_SDK=sdk):
        AndroidDistribution.locate()

    with self.distribution() as sdk:
      with env(ANDROID_SDK_HOME=sdk):
        AndroidDistribution.locate()

    with self.distribution() as sdk:
      with env(ANDROID_HOME=sdk):
        AndroidDistribution.locate(target_sdk='18')
      with env(ANDROID_HOME=sdk):
        AndroidDistribution.locate(build_tools_version='19.1.0')
      with env(ANDROID_HOME=sdk):
        AndroidDistribution.locate(target_sdk='18', build_tools_version='19.1.0')

# No live test for now, the varying installed platforms make that unpredictable.