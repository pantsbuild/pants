# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os


class AndroidDistribution(object):
  """
  This class looks for Android SDKs installed on the machine's path. The SDK path will not
  be verified until an Android task requests a tool.
  """

  # As of now, missing tools simply raise an exception. The SDK could be updated from
  # within this class, it just depends what state we want to leave the host machine afterwards.
  # There is probably a discussion to be had about bootstrapping as well.

  class Error(Exception):
    """Indicates an invalid android distribution."""

  _CACHED_SDK = {}

  @classmethod
  def cached(cls, path=None):
    """
    :param path:
    :return:
    """
    # The key just used for quick lookup. This method will generally be passed no params, and will
    # always cache the key(None). But a user can pass a specific sdk on the CLI through AndroidTask.
    key = (path)
    dist = cls._CACHED_SDK.get(key)
    if not dist:
      dist = cls.set_sdk_path(path)
    cls._CACHED_SDK[key] = dist
    return dist

  @classmethod
  def set_sdk_path(cls, path=None):
    def sdk_path(sdk_env_var):
      sdk = os.environ.get(sdk_env_var)
      return os.path.abspath(sdk) if sdk else None

    def search_path(path=None):
      # Check path if one is passed at instantiation, then check environmental variables
      if path:
        yield os.path.abspath(path)
      yield sdk_path('ANDROID_HOME')
      yield sdk_path('ANDROID_SDK_HOME')
      yield sdk_path('ANDROID_SDK')

    for path in filter(None, search_path(path)):
      dist = cls(path)
      return dist
    dist = cls(None)
    return dist

  def __init__(self, sdk_path=None):
    """Creates an Android distribution and caches tools for quick retrieval."""
    self._sdk_path = sdk_path
    self._validated_tools = set()

  def _register_file(self, tool):
    if tool not in self._validated_tools:
      if not os.path.isfile(tool):
        raise self.Error('There is no {0!r} installed.The Android SDK may need to be updated'
                         .format(tool))
      self._validated_tools.add(tool)
    return tool

  def registered_android_tool(self, tool_path):
    try:
      android_tool = os.path.join(self._sdk_path, tool_path)
    except:
        raise AndroidDistribution.Error('Failed to locate Android SDK. Please install SDK and '
                                    'set ANDROID_HOME in your path')
    self._register_file(android_tool)
    return android_tool

  def __repr__(self):
    return ('AndroidDistribution({0!r})'.format(self._sdk_path))