# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os

from pants.backend.android.tasks.android_task import AndroidTask


# These are hardcoded into aapt but we added 'BUILD*'. Changes clobber, so we need entire string.
IGNORED_ASSETS = ('!.svn:!.git:!.ds_store:!*.scc:.*:<dir>_*:!CVS:'
                  '!thumbs.db:!picasa.ini:!*~:BUILD*')

class AaptTask(AndroidTask):
  """Base class for tasks performed by the Android aapt tool."""
  @classmethod
  def register_options(cls, register):
    super(AaptTask, cls).register_options(register)
    register('--target-sdk',
             help='Use this Android SDK to compile resources. Overrides AndroidManifest.xml.')
    register('--build-tools-version',
             help='Use this Android build-tools version to compile resources.')
    register('--ignored-assets', default=IGNORED_ASSETS, metavar='<PATTERN>',
             help='Patterns the aapt tools should ignore as they search the resource_dir.')

  @classmethod
  def package_path(cls, package):
    """Return the package name translated into a path"""
    return package.replace('.', os.sep)

  def __init__(self, *args, **kwargs):
    super(AaptTask, self).__init__(*args, **kwargs)
    self._android_dist = self.android_sdk
    self._forced_build_tools_version = self.get_options().build_tools_version
    self.ignored_assets = self.get_options().ignored_assets
    self._forced_target_sdk = self.get_options().target_sdk

  def aapt_tool(self, build_tools_version):
    """Return the appropriate aapt tool.

    :param string build_tools_version: The Android build-tools version number (e.g. '19.1.0').
    """
    if self._forced_build_tools_version:
      build_tools_version = self._forced_build_tools_version
    aapt = os.path.join('build-tools', build_tools_version, 'aapt')
    return self._android_dist.register_android_tool(aapt)

  def android_jar_tool(self, target_sdk):
    """Return the appropriate android.jar.

    :param string target_sdk: The Android SDK version number of the target (e.g. '18').
    """
    if self._forced_target_sdk:
      target_sdk = self._forced_target_sdk
    android_jar = os.path.join('platforms', 'android-' + target_sdk, 'android.jar')
    return self._android_dist.register_android_tool(android_jar)

