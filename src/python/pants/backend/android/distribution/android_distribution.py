# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os

from twitter.common import log


class AndroidDistribution(object):
  """
  This class looks for Android SDks installed on the machine's path. It then verifies that that
  SDK has the needed build-tools and API levels installed. There is caching of most lookups.
  """

  # As of now, missing API or build-tools only raises an exception. The SDK could be updated from
  # within this class, it just depends what state we want to leave the host machine afterwards.
  # There is probably a discussion to be had about bootstrapping as well.

  # Good portions of this are inspired by pants.java.distribution. The two distributions could
  # perhaps benefit from a refactor that makes some of the validation process common.

  class Error(Exception):
    """Indicates an invalid android distribution."""

  _CACHED_SDK = {}

  @classmethod
  def cached(cls, target_sdk=None, build_tools_version=None):
    # Tuple just used for quick lookup. This method will generally be passed no params, and will
    # always cache the key(None, None). But it stops us from crawling the user path each invocation.
    key = (target_sdk, build_tools_version)
    dist = cls._CACHED_SDK.get(key)
    if not dist:
      dist = cls.locate()
    cls._CACHED_SDK[key] = dist
    return dist


  @classmethod
  def locate(cls, target_sdk=None, build_tools_version=None):
    def sdk_path(sdk_env_var):
      sdk = os.environ.get(sdk_env_var)
      return os.path.abspath(sdk) if sdk else None

    def search_path():
      yield sdk_path('ANDROID_HOME')
      yield sdk_path('ANDROID_SDK_HOME')
      yield sdk_path('ANDROID_SDK')

    for path in filter(None, search_path()):
      dist = cls(path)
      return dist
    dist = cls(None)
    return dist

  def __init__(self, sdk_path=None, target_sdk=None, build_tools_version=None):
    """Creates an Android distribution wrapping the given sdk_path."""

    if not os.path.isdir(sdk_path):
      raise ValueError('The specified android sdk path is invalid: %s' % sdk_path)
    self._sdk_path = sdk_path
    self._validated_tools = set()

  def _validated_executable(self, tool):
    if tool not in self._validated_tools:
      self._validate_executable(tool)
      self._validated_tools.add(tool)
    return tool

  def _validated_tool(self, tool):
    if tool not in self._validated_tools:
      self._validate_file(tool)
      self._validated_tools.add(tool)
    return tool

  def _validate_executable(self, tool):
    if not self._is_executable(tool):
      raise self.Error('Failed to locate the %s executable. It does not appear to be an'
                       ' installed portion of this %s' % (tool, 'Android SDK'))
    return tool

  def _validate_file(self, tool):
    if not os.path.isfile(tool):
      raise self.Error('Failed to locate the %s file. It does not appear to be an'
                       ' installed portion of this %s' % (tool, 'Android SDK'))
    return tool

  @staticmethod
  def _is_executable(path):
    return os.path.isfile(path) and os.access(path, os.X_OK)

  def android_jar_tool(self, target_sdk):
    """The android.jar holds the class files with the Android APIs, unique per platform"""
    if not self._sdk_path:
      raise AndroidDistribution.Error('Failed to locate Android SDK. Please install SDK and '
                                      'set ANDROID_HOME in your path')
    android_jar = os.path.join(self._sdk_path, 'platforms', 'android-' + target_sdk, 'android.jar')
    return self._validated_tool(android_jar)

  def aapt_tool(self, build_tools_version):
    """returns aapt tool for each unique build-tools version. Used to validate build-tools path"""
    if not self._sdk_path:
      raise AndroidDistribution.Error('Failed to locate Android SDK. Please install SDK and '
                      'set ANDROID_HOME in your path')
    aapt = os.path.join(self._sdk_path, 'build-tools', build_tools_version, 'aapt')
    return self._validated_executable(aapt)

  def __repr__(self):
    return ('AndroidDistribution({0!r})'.format(self._sdk_path))
