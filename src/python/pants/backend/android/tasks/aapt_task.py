# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pants.backend.android.tasks.android_task import AndroidTask


# These are hardcoded into aapt but we added 'BUILD*'. Changes clobber, so we need entire string
IGNORED_ASSETS = ('!.svn:!.git:!.ds_store:!*.scc:.*:<dir>_*:!CVS:'
                  '!thumbs.db:!picasa.ini:!*~:BUILD*')

class AaptTask(AndroidTask):
  """ Base class for tasks performed by the Android aapt tool"""
  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    #TODO(mateor) Ensure a change of target-sdk or build-tools rebuilds product w/o clean
    super(AaptTask, cls).setup_parser(option_group, args, mkflag)

    option_group.add_option(mkflag("target-sdk"), dest="target_sdk",
                            help="[%default] Specifies the target Android SDK used to compile "
                                 "resources. Overrides AndroidManifest.xml.")

    option_group.add_option(mkflag("build-tools-version"), dest="build_tools_version",
                            help="[%default] Specifies the Android build-tools version used "
                                 "to compile resources.")

    option_group.add_option(mkflag("ignored-assets"), dest="ignored_assets", default=IGNORED_ASSETS,
                            help="[%default] Specifies regex patterns the aapt tools should "
                                 "ignore as it spiders down the resource_dir.")

  @classmethod
  def package_path(cls, package):
    """Return the package name translated into a path"""
    return package.replace('.', os.sep)

  def __init__(self, *args, **kwargs):
    super(AaptTask, self).__init__(*args, **kwargs)
    self._android_dist = self.android_sdk
    self._forced_build_tools_version = self.context.options.build_tools_version
    if self.context.options.ignored_assets:
      self.ignored_assets = self.context.options.ignored_assets
    else:
      self.ignored_assets = IGNORED_ASSETS
    self._forced_target_sdk = self.context.options.target_sdk

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

