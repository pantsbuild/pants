# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os


class AndroidDistribution(object):
  """Represents an Android SDK distribution.
  """

  class DistributionError(Exception):
    """Indicates an invalid android distribution."""

  class MissingToolError(Exception):
    """Indicates a missing tool at SDK location.

    The sdk_path has been either passed at invocation or as environmental variable but the needed
    tool cannot be found.
    """

  _CACHED_SDK = {}

  @classmethod
  def cached(cls, path=None):
    """
    Check for cached SDK. If not found, instantiate class and search for local SDK.

    :param string path: Optional local address of an SDK, set by user as an option.
    :returns: a new :class:``pants.backend.android.distribution.AndroidDistribution``.
    """
    dist = cls._CACHED_SDK.get(path)
    if not dist:
      dist = cls.locate_sdk_path(path)
    cls._CACHED_SDK[path] = dist
    return dist

  @classmethod
  def locate_sdk_path(cls, path=None):
    """
    Locate an Android SDK by checking for traditional environmental aliases.

    This method returns an AndroidDistribution even if there is no valid SDK on the user's path.
    The SDK is not validated until an actual tool or the sdk_path is requested by a task using
    AndroidDistribution.register_android_tool() or AndroidDistribution.sdk_path.

    :param string path: Optional local address of a SDK, set by user as an option.
    """
    def sdk_path(sdk_env_var):
      sdk = os.environ.get(sdk_env_var)
      return os.path.abspath(sdk) if sdk else None

    def search_path(path):
      # Check path if one is passed at instantiation, then check environmental variables.
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
    self._sdk = None
    self._validated_tools = {}


  @property
  def sdk_path(self):
    """Return the full path of the validated Android sdk."""
    if not self._sdk:
      if os.path.isdir(self._sdk_path):
        self._sdk = self._sdk_path
      else:
        raise self.DistributionError('Failed to locate Android SDK. Please install '
                                     'SDK and set ANDROID_HOME in your path.')
    return self._sdk

  def register_android_tool(self, tool_path):
    """Check tool located at tool_path and see if it is installed in the local Android SDK.

    All android tasks should request their tools using this method. Tools are validated and then
    cached for quick lookup.
    :param string tool_path: Path to tool, relative to the Android SDK root, e.g
      'platforms/android-19/android.jar'.
    """
    if tool_path not in self._validated_tools:
      android_tool = os.path.join(self.sdk_path, tool_path)
      if os.path.isfile(android_tool):
        # Use entire relative path as a key since the SDK usually has multiple copies of each tool.
        self._validated_tools[tool_path] = android_tool
      else:
        raise self.MissingToolError('There is no {} installed.The Android SDK may need to be '
                                    'updated.'.format(android_tool))
    return self._validated_tools[tool_path]

  def __repr__(self):
    return 'AndroidDistribution({})'.format(self._sdk_path)
