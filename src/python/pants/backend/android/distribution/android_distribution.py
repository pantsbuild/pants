# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import shutil

from pants.util.dirutil import safe_mkdir


class AndroidDistribution(object):
  """Represent an Android SDK distribution."""

  class DistributionError(Exception):
    """Indicate an invalid android distribution."""

  _CACHED_SDK = {}

  @classmethod
  def cached(cls, path=None):
    """Return an AndroidDistribution and cache results.

    :param string path: Optional path of an Android SDK installation.
    :return: An android distribution.
    :rtype: AndroidDistribution
    """
    dist = cls._CACHED_SDK.get(path)
    if not dist:
      dist = cls.locate_sdk_path(path)
      cls._CACHED_SDK[path] = dist
    return dist

  @classmethod
  def locate_sdk_path(cls, path=None):
    """Locate an Android SDK by checking any passed path and then traditional environmental aliases.

    :param string path: Optional local address of a SDK.
    :return: An android distribution.
    :rtype: AndroidDistribution
    :raises: ``DistributionError`` if SDK cannot be found.
    """
    def sdk_path(sdk_env_var):
      """Return the full path of environmental variable sdk_env_var."""
      sdk = os.environ.get(sdk_env_var)
      return os.path.abspath(sdk) if sdk else None

    def search_path(path):
      """Find a Android SDK home directory."""
      if path:
        yield os.path.abspath(path)
      yield sdk_path('ANDROID_HOME')
      yield sdk_path('ANDROID_SDK_HOME')
      yield sdk_path('ANDROID_SDK')

    for path in filter(None, search_path(path)):
      dist = cls(sdk_path=path)
      return dist
    raise cls.DistributionError('Failed to locate Android SDK. Please install '
                                'SDK and set ANDROID_HOME in your path.')

  def __init__(self, sdk_path):
    """Create an Android distribution and cache tools for quick retrieval."""
    self._sdk_path = sdk_path
    self._validated_tools = {}

  def register_android_tool(self, tool_path, workdir=None):
    """Return the full path for the tool at SDK location tool_path or of a copy under workdir.

    All android tasks should request their tools using this method.
    :param string tool_path: Path to tool, relative to the Android SDK root, e.g
      'platforms/android-19/android.jar'.
    :param string workdir: Location for the copied file. Pants will put a copy of the
      android file under workdir.
    :return: Full path to either the tool or a created copy of that tool.
    :rtype: string
    :raises: ``DistributionError`` if tool cannot be found.
    """
    if tool_path not in self._validated_tools:
      android_tool = self._get_tool_path(tool_path)
      # If an android file is bound for the classpath it must be under buildroot, so create a copy.
      if workdir:
        copy_path = os.path.join(workdir, tool_path)
        if not os.path.isfile(copy_path):
          try:
            safe_mkdir(os.path.dirname(copy_path))
            shutil.copy(android_tool, copy_path)
          except OSError as e:
            raise self.DistributionError('Problem creating copy of the android tool: {}'.format(e))
        self._validated_tools[tool_path] = copy_path
      else:
        self._validated_tools[tool_path] = android_tool
    return self._validated_tools[tool_path]

  def _get_tool_path(self, tool_path):
    """Return full path of tool if it is found on disk."""
    android_tool = os.path.join(self._sdk_path, tool_path)
    if os.path.isfile(android_tool):
      return android_tool
    else:
      raise self.DistributionError('There is no {} installed. The Android SDK may need to be '
                                   'updated.'.format(android_tool))

  def __repr__(self):
    return 'AndroidDistribution({})'.format(self._sdk_path)
