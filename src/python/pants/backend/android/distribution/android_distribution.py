# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
from twitter.common import log

class AndroidDistribution(object):
  """
  Placeholder class for finding ANDROID_SDK_HOME, until a decision on whether/how
  to bootstrap tools is reached.

  If we use the local Android SDK, it might make sense to refactor 'distribution'
  out of the "java" package and subclass handling for Android SDK along with the JDK/JRE.

  If we keep android distribution separate, then this will be fleshed out and error-catched.
  """
  #TODO: Refactor cloned code from Distribution, in some way that is agreeable to upstream.


  class Error(Exception):
    """Indicates an invalid java distribution."""

  _CACHED_SDK = {}
  _CACHED_COUNT = 0 #debug

  @classmethod
  def cached(cls, target_sdk=None, build_tools_version=None):
    def scan_constraint_match():
      for dist in cls._CACHED_SDK.values():
        print ("doing scan_target")
        print ('target sdk is %s' % (target_sdk))
        if target_sdk and not dist.locate_target_sdk(target_sdk): # == target_sdk: (?)
          print ("we had both as True")
          continue
        print ('build_tools_version is %s' % (build_tools_version))
        print ("doing scan_build")
        if build_tools_version and not dist.locate_build_tools(build_tools_version): # == build_tools_version:
          continue
        return dist


    # this could be more efficient by far
    key = (target_sdk, build_tools_version) # tuple caching particular pair. not ideal.
    dist = cls._CACHED_SDK.get(key)
    if not dist:
      dist = scan_constraint_match()
      if not dist:
        # This locate call is the only place that makes new Dists
        dist = cls.locate(target_sdk=target_sdk, build_tools_version=build_tools_version)
        cls._CACHED_COUNT += 1 #debug
    # All that happens here is caching a new key, not certainly making a new dist.
    cls._CACHED_SDK[key] = dist
    return dist


  @classmethod
  def locate(cls, target_sdk=None, build_tools_version=None):
    print ("locating")
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
        dist.validate()
        log.debug('Located %s' % ('SDK'))
        return dist
      except (ValueError, cls.Error):
        pass
    raise cls.Error('Failed to locate %s. Please set ANDROID_HOME in your path' % ('Android SDK'))


  #create a distribution (aapt, all the rest of tools as needed)
  def __init__(self, sdk_path, target_sdk=None, build_tools_version=None):
    if not os.path.isdir(sdk_path):
      raise ValueError('The specified android sdk path is invalid: %s' % sdk_path)
    self._sdk_path = sdk_path
    self._target_sdk = target_sdk
    self._build_tools_version = build_tools_version
    self._validated_sdks = set()
    self._validated_build_tools = set()
    self._validated_binaries = {}
    self._installed_build_tools = {}         # do I still need this?

  @property
  def target_sdk(self):
    return self.locate_target_sdk()


  def locate_target_sdk(self, target_sdk):
    print ("here is locate_target")
    if target_sdk not in self._validated_sdks:  #TODO do I need to check for empty here and at the scan_constraint_match
      try:
      # args = self.android_tool, 'list', 'sdk', '|', 'grep', '"API level"', target_sdk
      # if args
        #return
      #else exception ("Need to update SDK and download SDK %s", target_sdk)
        self._validated_sdks.add(target_sdk)
        return True
      except self.Error:
        raise
    print ("we are about to return True in locate_target")
    return True # TODO something better than this I bet.

  def locate_build_tools(self, build_tools_version):
    print ("here is locate_build_tools")
    if build_tools_version not in self._validated_build_tools:
      try:
        # validated_binary(aapt) ? I don't think that is helpful, since we need a specific aapt.
        # os. executable file exists at self._sdk_path/build-tools/build_tools_version/aapt (for checking purposes)
        self._validated_build_tools.add(build_tools_version)
        return True
      except self.Error:
        raise
    print ("we are about to return True in locate_target")
    return True

  def validate(self):

    if self._target_sdk:
      target = self._target_sdk
      if target and not self.locate_target_sdk(target):
        print ("error validating target_sdk")
        raise self.Error('The Android SDK at %s does not have the %s API installed and'
                         ' must be updated to build this target' % (self._sdk_path, target))
    if self._build_tools_version:
      build_tools = self._build_tools_version
      if build_tools and not self.locate_build_tools(build_tools):
        print ("error validating build_tools")
        raise self.Error('The Android SDK at %s does not have build tools version %s and must be '
                         'updated to build this target' % (self._sdk_path, self._build_tools_version))

  def _validated_executable(self, tool):
    exe = self._validated_binaries.get(tool)
    if not exe:
      exe = self._validate_executable(tool)
      self._validated_binaries[tool] = exe
    return exe

  def _validate_executable(self, tool):
    if not self._is_executable(tool):
      raise self.Error('Failed to locate the %s executable, %s does not appear to be a'
                       ' valid %s' % (tool, self, 'Android SDK'))
    return tool

  @staticmethod
  def _is_executable(path):
    return os.path.isfile(path) and os.access(path, os.X_OK)

  #The android tool is used to manage the SDK itself....staying here for now.
  def android_tool(self):
    return (os.path.join(self._sdk_path, 'tools','android'))

  def __repr__(self):
    return ('AndroidDistribution(%r, target_sdk=%r, build_tools_version=%r)'
            % (self._sdk_path, self._target_sdk, self._build_tools_version))