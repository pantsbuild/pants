# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

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

  def register_tool_link(self, tool_path, workdir):
    """Verify presence of tool at SDK location tool_path and return a link to that file.

    Pants requires that classpath entries be underneath the buildroot. Android
    tasks that add Android SDK jars to the classpath should use this method.
    :param string tool_path: Path to tool, relative to the Android SDK root, e.g
      'platforms/android-19/android.jar'.
    :param string workdir: The workdir of the task requesting the tool.
    :return: Full path to hard link of the android tool.
    :rtype: string
    :raises: ``DistributionError`` if tool cannot be found.
    """
    if tool_path not in self._validated_tools:
      android_tool = self._get_tool_path(tool_path)
      link_path = os.path.join(workdir, os.path.basename(tool_path))
      if not os.path.isfile(link_path):
        safe_mkdir(workdir)
        try:
          os.link(android_tool, link_path)
        except OSError as e:
          raise self.DistributionError('Problem creating a link to the android tool: ', e)
      self._validated_tools[tool_path] = link_path
    return self._validated_tools[tool_path]

  def register_android_tool(self, tool_path):
    """Verify presence of tool at SDK location tool_path and return the full path.

    All android tasks should request their tools using this method.
    :param string tool_path: Path to tool, relative to the Android SDK root, e.g
      'platforms/android-19/android.jar'.
    :return: Full path to android tool.
    :rtype: string
    :raises: ``DistributionError`` if tool cannot be found.
    """
    if tool_path not in self._validated_tools:
      android_tool = self._get_tool_path(tool_path)
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
