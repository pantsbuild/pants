# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
from twitter.common import log


class AndroidDistribution(object):
  """
  TODO: (Update docstring for class and methods)
  Placeholder class for finding ANDROID_SDK_HOME, until a decision on whether/how
  to bootstrap tools is reached.

  If we use the local Android SDK, it might make sense to refactor 'distribution'
  out of the "java" package and subclass handling for Android SDK along with the JDK/JRE.

  If we keep android distribution separate, then this will be fleshed out and error-catched.
  """

  class Error(Exception):
    """Indicates an invalid java distribution."""

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

    # this tuple just  used for quick lookup. If no match we check the validated sets in locate()
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
      try:
        dist = cls(path, target_sdk=target_sdk, build_tools_version=build_tools_version)
        dist.validate(target_sdk, build_tools_version)
        log.debug('Located %s' % ('SDK'))
        return dist
      except (ValueError, cls.Error):
        pass
    raise cls.Error('Failed to locate %s. Please set ANDROID_HOME in your path' % ('Android SDK'))

  def __init__(self, sdk_path, target_sdk=None, build_tools_version=None):
    """Creates a distribution wrapping the given bin_path.

    :param _sdk_path: the path to the installed SDK
    :param set _installed_sdks: verified API levels installed in the _sdk_path
    :param set _installed_build_tools: verified build-tools versions installed in _sdk_path
    """

    if not os.path.isdir(sdk_path):
      raise ValueError('The specified android sdk path is invalid: %s' % sdk_path)
    self._sdk_path = sdk_path
    self._installed_sdks = set()
    self._installed_build_tools = set()
    self._validated_binaries = set()

  def validate(self, target_sdk, build_tools_version):
    if target_sdk and not self.locate_target_sdk(target_sdk):
      raise self.Error('The Android SDK at %s does not have the %s API installed and '
                       'must be updated to build this target' % (self._sdk_path, target_sdk))
    if build_tools_version and not self.locate_build_tools(build_tools_version):
      raise self.Error('The Android SDK at %s does not have build tools version %s and must be '
                       'updated to build this target' % (self._sdk_path, build_tools_version))

  def locate_target_sdk(self, target_sdk):
    """Checks to see if the requested API is installed in Android SDK.

    NB: This can be done from the CLI with "$ANDROID_TOOL list targets | grep "API level $TARGET"
    But that $ANDROID_TOOL is simply checking for the physical presence of a few files. I am open
    to adding additional checks for a couple other SDK and Build-tools binaries. """
    if target_sdk not in self._installed_sdks:
      try:
      #else exception ("Need to update SDK and download SDK %s", target_sdk)
        self._installed_sdks.add(target_sdk)
      except self.Error:
        raise
    return True

  def locate_build_tools(self, build_tools_version):
    """This looks to see if the requested version of the Android build tools are installed
    AndroidTargets default to the latest stable release of the build tools. But this can be
    overriden in the BUILD file.

    There is no decent way to check installed build tools, we must be content with verifying the
    presence of a representative executable (aapt).
    """
    if build_tools_version not in self._installed_build_tools:
      try:
        aapt = self.aapt_tool(build_tools_version)
        self._validated_executable(aapt)
      except self.Error:
        raise
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

  def android_tool(self):
    """The android tool is used to manage the SDK itself """
    return (os.path.join(self._sdk_path, 'tools','android'))

  def aapt_tool(self, build_tools_version):
    return (os.path.join(self._sdk_path, 'build-tools', build_tools_version, 'aapt'))

  def __repr__(self):
    return ('AndroidDistribution(%r, installed_sdks=%r, installed_build_tools=%r)'
            % (self._sdk_path, list(self._installed_sdks), list(self._installed_build_tools)))
