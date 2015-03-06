# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from contextlib import contextmanager

from pants.backend.android.distribution.android_distribution import AndroidDistribution
from pants.util.contextutil import environment_as, temporary_dir
from pants_test.android.test_android_base import TestAndroidBase


class TestAndroidDistribution(TestAndroidBase):
  """Test the AndroidDistribution class."""

  @contextmanager
  def env(self, **kwargs):
    environment = dict(ANDROID_HOME=None, ANDROID_SDK_HOME=None, ANDROID_SDK=None)
    environment.update(**kwargs)
    with environment_as(**environment):
      yield

  def setUp(self):
    super(TestAndroidDistribution, self).setUp()
    # Save local cache and then flush so tests get a clean environment. Cache restored in tearDown.
    self._local_cache = AndroidDistribution._CACHED_SDK
    AndroidDistribution._CACHED_SDK = {}

  def tearDown(self):
    super(TestAndroidDistribution, self).tearDown()
    AndroidDistribution._CACHED_SDK = self._local_cache

  def test_passing_sdk_path(self):
    with self.distribution() as sdk:
      android_sdk = AndroidDistribution(sdk_path=sdk)
      aapt = os.path.join(sdk, 'build-tools', '19.1.0', 'aapt')
      android_tool = android_sdk.register_android_tool(aapt)
      self.assertEquals(android_tool, os.path.join(sdk, aapt))

  def test_passing_sdk_path_not_valid(self):
    with self.assertRaises(AndroidDistribution.DistributionError):
      sdk = os.path.join('/no', 'sdk', 'here')
      aapt = os.path.join(sdk, 'build-tools', '19.1.0', 'aapt')
      AndroidDistribution(sdk_path=sdk).register_android_tool(aapt)

  def test_passing_sdk_path_missing_tools(self):
    with self.assertRaises(AndroidDistribution.DistributionError):
      with self.distribution() as sdk:
        aapt = os.path.join(sdk, 'build-tools', 'bad-number', 'aapt')
        AndroidDistribution(sdk_path=sdk).register_android_tool(aapt)

  def test_locate_no_sdk_on_path(self):
    with self.assertRaises(AndroidDistribution.DistributionError):
      with self.distribution() as sdk:
        with self.env(ANDROooooD_HOME=sdk):
          dist = AndroidDistribution.locate_sdk_path()
          self.assertEquals(dist._sdk_path, None)

  def test_locate_sdk_path(self):
    with self.distribution() as sdk:
      with self.env(ANDROID_HOME=sdk):
        dist = AndroidDistribution.locate_sdk_path()
        self.assertEquals(dist._sdk_path, sdk)

  def test_locate_alternative_variables(self):
    # Test that alternative environmental variables are accepted.
    with self.distribution() as sdk:
      with self.env(ANDROID_SDK=sdk):
        dist = AndroidDistribution.locate_sdk_path()
        self.assertEquals(dist._sdk_path, sdk)

  def test_caching_multiple_sdks(self):
    with self.distribution() as first_sdk_path:
      with self.distribution() as second_sdk_path:
        first_sdk_instance = AndroidDistribution.cached(first_sdk_path)
        second_sdk_instance = AndroidDistribution.cached(second_sdk_path)
        self.assertEquals(AndroidDistribution._CACHED_SDK[first_sdk_path], first_sdk_instance)
        self.assertEquals(AndroidDistribution._CACHED_SDK[second_sdk_path], second_sdk_instance)

  def test_sdk_path(self):
    with self.distribution() as sdk:
      android_sdk = AndroidDistribution.cached(sdk)
      self.assertEquals(sdk, android_sdk._sdk_path)

  def test_empty_sdk_path(self):
    # Shows that an AndroidDistribution can be created as long as an sdk path is declared.
    with temporary_dir() as sdk:
      android_sdk = AndroidDistribution.cached(sdk)
      self.assertEquals(android_sdk._sdk_path, sdk)

  def test_sdk_path_is_none(self):
    with self.assertRaises(AndroidDistribution.DistributionError):
      with self.env() as sdk:
        AndroidDistribution.cached(sdk)

  def test_validate_bad_path(self):
    # The SDK path is not validated until the tool is registered.
    sdk = os.path.join('/no', 'sdk', 'here')
    android_sdk = AndroidDistribution.cached(sdk)
    self.assertEquals(sdk, android_sdk._sdk_path)

  def test_register_android_tool(self):
    with self.distribution() as sdk:
      android_sdk = AndroidDistribution.cached(sdk)
      aapt = os.path.join('build-tools', '19.1.0', 'aapt')
      registered_aapt = android_sdk.register_android_tool(aapt)
      self.assertEquals(registered_aapt, os.path.join(sdk, aapt))

  def test_register_android_tool_bad_sdk(self):
    with self.assertRaises(AndroidDistribution.DistributionError):
      sdk = os.path.join('/no', 'sdk', 'here')
      android_sdk = AndroidDistribution.cached(sdk)
      aapt = os.path.join('build-tools', '19.1.0', 'aapt')
      android_sdk.register_android_tool(aapt)

  def test_register_nonexistent_android_tool(self):
    with self.assertRaises(AndroidDistribution.DistributionError):
      with self.distribution() as sdk:
        android_sdk = AndroidDistribution.cached(sdk)
        android_sdk.register_android_tool(os.path.join('build-tools', '19.1.0', 'random_tool'))

  def test_validated_tools(self):
    with self.distribution() as sdk:
      android_sdk = AndroidDistribution.cached(sdk)
      aapt = os.path.join('build-tools', '19.1.0', 'aapt')
      android_sdk.register_android_tool(aapt)
      self.assertIn(aapt, android_sdk._validated_tools)
