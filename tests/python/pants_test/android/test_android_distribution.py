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
  
  def setUp(self):
    super(TestAndroidDistribution, self).setUp()
    # Save local cache and then flush so tests get a clean environment. Cache restored in tearDown.
    self._local_cache = AndroidDistribution._CACHED_SDK
    AndroidDistribution._CACHED_SDK = {}

  def tearDown(self):
    super(TestAndroidDistribution, self).tearDown()
    AndroidDistribution._CACHED_SDK = self._local_cache
    
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

  def test_sdk_path(self):
    with self.distribution() as sdk:
      android_sdk = AndroidDistribution.cached(sdk)
      self.assertEquals(sdk, android_sdk.sdk_path)

  def test_allows_bad_path(self):
    # This test shows that AndroidDistribution can be instantiated with an invalid path.
    sdk = '/no/sdk/here'
    AndroidDistribution.cached(sdk)

  def test_validate_no_sdk_at_path(self):
    # SDK paths are checked lazily, this shows the exception now is raised.
    with self.assertRaises(AndroidDistribution.Error):
      sdk = '/no/sdk/here'
      android_sdk = AndroidDistribution.cached(sdk)
      self.assertEquals(sdk, android_sdk.sdk_path)
    
  def test_register_android_tool(self):
    with self.distribution() as sdk:
      android_sdk = AndroidDistribution.cached(sdk)
      android_sdk.register_android_tool(os.path.join('build-tools', '19.1.0', 'aapt'))

  def test_register_uninstalled_android_tool(self):
    with self.assertRaises(AndroidDistribution.Error):
      with self.distribution() as sdk:
        android_sdk = AndroidDistribution.cached(sdk)
        android_sdk.register_android_tool(os.path.join('build-tools', '19.1.0', 'random_tool'))
      