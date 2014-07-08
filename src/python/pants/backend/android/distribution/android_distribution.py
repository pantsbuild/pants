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
    def scan_constraint_match():
      for dist in cls._CACHED_SDK.values():
        if target_sdk and not dist.locate_target_sdk(target_sdk):
          continue
        if build_tools_version and not dist.locate_build_tools(build_tools_version):
          continue
        return dist

    # tuple just used for quick lookup. If no match, check within validated sets w/ locate()
    key = (target_sdk, build_tools_version)
    dist = cls._CACHED_SDK.get(key)
    if not dist:
      dist = scan_constraint_match()
      if not dist:
        dist = cls.locate(target_sdk=target_sdk, build_tools_version=build_tools_version)
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
      dist = cls(path, target_sdk=target_sdk, build_tools_version=build_tools_version)
      log.debug('Validated %s' % ('Android SDK'))
      return dist
    raise cls.Error('Failed to locate %s. Please set install SDK and '
                    'set ANDROID_HOME in your path' % ('Android SDK'))

  def __init__(self, sdk_path=None, target_sdk=None, build_tools_version=None):
    """Creates an Android distribution wrapping the given sdk_path."""

    if not os.path.isdir(sdk_path):
      raise ValueError('The specified android sdk path is invalid: %s' % sdk_path)
    self._sdk_path = sdk_path
    self._installed_sdks = set()
    self._installed_build_tools = set()
    self._validated_binaries = set()
    self.validate(target_sdk, build_tools_version)

  def validate(self, target_sdk, build_tools_version):
    if target_sdk and not self.locate_target_sdk(target_sdk):
      raise self.Error('There is no Android SDK at %s with API level %s installed. It may need '
                       'to be updated' % (self._sdk_path, target_sdk))
    if build_tools_version and not self.locate_build_tools(build_tools_version):
      raise self.Error('There is no Android SDK at %s with build-tools version %s installed. '
                       'It may need to be updated' % (self._sdk_path, build_tools_version))

  def locate_target_sdk(self, target_sdk):
    """Checks to see if the requested API is installed in Android SDK."""

    # NB: Can be done from CLI with "$ANDROID_TOOL list targets | grep "API level $TARGET"
    # But that $ANDROID_TOOL is simply checking for the physical presence of a few files.
    if target_sdk not in self._installed_sdks:
      android_jar = self.android_jar_tool(target_sdk)
      if not os.path.isfile(android_jar):
        return False
      self._installed_sdks.add(target_sdk)
    return True

  def locate_build_tools(self, build_tools_version):
    """This looks to see if the requested version of the Android build tools are installed.
    AndroidTargets default to the latest stable release of the build tools, but that can be
    overriden in the BUILD file.
    """
    #I found no decent way to check installed build tools, we must be content with verifying
    #the presence of a representative executable (aapt in this case).

    if build_tools_version not in self._installed_build_tools:
      try:
        aapt = self.aapt_tool(build_tools_version)
        self._validated_executable(aapt)
      except:
        return False
    self._installed_build_tools.add(build_tools_version)
    return True

  def _validated_executable(self, tool):
    if tool not in self._validated_binaries:
      self._validate_executable(tool)
      self._validated_binaries.add(tool)
    return tool

  def _validate_executable(self, tool):
    if not self._is_executable(tool):
      raise self.Error('Failed to locate the %s executable. It does not appear to be an'
                       ' installed portion of this %s' % (tool, 'Android SDK'))
    return tool

  @staticmethod
  def _is_executable(path):
    return os.path.isfile(path) and os.access(path, os.X_OK)

  def android_jar_tool(self, target_sdk):
    """The android.jar holds the class files with the Android APIs, unique per platform"""
    return os.path.join(self._sdk_path, 'platforms', 'android-' + target_sdk, 'android.jar')

  def aapt_tool(self, build_tools_version):
    """returns aapt tool for each unique build-tools version. Used to validate build-tools path"""
    return os.path.join(self._sdk_path, 'build-tools', build_tools_version, 'aapt')

  def __repr__(self):
    return ('AndroidDistribution({0!r}, installed_sdks={1!r}, installed_build_tools={2!r})'.format
            (self._sdk_path, list(self._installed_sdks), list(self._installed_build_tools)))
