# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os


class AndroidDistribution(object):
  """
  Represents the Android SDK on the local system.
  """

  class Error(Exception):
    """Indicates an invalid android distribution."""

  _CACHED_SDK = {}

  @classmethod
  def cached(cls, path=None):
    """
    Check for cached SDK. If not found, instantiate class and search for local SDK.

    :param string path: Optional local address of an SDK, set by user in CLI invocation.
    :returns: a new :class:``pants.backend.android.distribution.AndroidDistribution``.
    """
    key = path
    dist = cls._CACHED_SDK.get(key)
    if not dist:
      dist = cls.locate_sdk_path(path)
    cls._CACHED_SDK[key] = dist
    return dist

  @classmethod
  def locate_sdk_path(cls, path=None):
    """
    Locate an Android SDK by checking for traditional environmental aliases.

    This method returns an AndroidDistribution even if there is no valid SDK on the user's path.
    There is no verification of valid SDK until an actual tool is requested by a task using
    AndroidDistribution.register_android_tool()

    :param string path: Optional local address of a SDK, set by user in CLI invocation.
    """
    def sdk_path(sdk_env_var):
      sdk = os.environ.get(sdk_env_var)
      return os.path.abspath(sdk) if sdk else None

    def search_path(path):
      # Check path if one is passed at instantiation, then check environmental variables
      if path:
        yield os.path.abspath(path)
      yield sdk_path('ANDROID_HOME')
      yield sdk_path('ANDROID_SDK_HOME')
      yield sdk_path('ANDROID_SDK')

    for path in filter(None, search_path(path)):
      dist = cls(sdk_path=path)
      return dist
    dist = cls(sdk_path=None)
    return dist

  def __init__(self, sdk_path=None):
    """Create an Android distribution and cache tools for quick retrieval."""
    self._sdk_path = sdk_path
    self._validated_tools = set()

  def register_android_tool(self, tool_path):
    """Check tool_path and see if it is installed in the local Android SDK.

    All android tasks should request their tools using this method. Tools are validated
    and cached for quick lookup. This is where the _sdk_path is validated.

    :param string tool_path: Path to tool, relative to the Android SDK root, e.g
      'platforms/android-19/android.jar'.
    """
    try:
      android_tool = os.path.join(self._sdk_path, tool_path)
    except:
      raise AndroidDistribution.Error('Failed to locate Android SDK. Please install SDK and '
                                      'set ANDROID_HOME in your path')
    self._register_file(android_tool)
    return android_tool

  def _register_file(self, tool):
    if tool not in self._validated_tools:
      if not os.path.isfile(tool):
        raise self.Error('There is no {0!r} installed.The Android SDK may need to be updated'
                         .format(tool))
      self._validated_tools.add(tool)
    return tool

  def __repr__(self):
    return ('AndroidDistribution({0!r})'.format(self._sdk_path))
