# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.contrib.android.targets.android_binary import AndroidBinary
from pants.contrib.android.tasks.android_task import AndroidTask


# These are hardcoded into aapt but we added 'BUILD*'. Changes clobber, so we need entire string.
# TODO(mateor) add a test to prove this is working.
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
    """Return the package name translated into a path."""
    return package.replace('.', os.sep)

  @staticmethod
  def is_android_binary(target):
    """Return True for AndroidBinary targets."""
    return isinstance(target, AndroidBinary)

  def __init__(self, *args, **kwargs):
    super(AaptTask, self).__init__(*args, **kwargs)
    self._forced_build_tools_version = self.get_options().build_tools_version
    self.ignored_assets = self.get_options().ignored_assets
    self._forced_target_sdk = self.get_options().target_sdk

  def aapt_tool(self, binary):
    """Return the appropriate aapt tool.

    :param AndroidBinary binary: AndroidBinary that requires the output of the aapt invocation.
    """
    build_tools_version = self._forced_build_tools_version or binary.build_tools_version
    aapt = os.path.join('build-tools', build_tools_version, 'aapt')
    return self.android_sdk.register_android_tool(aapt)

  def android_jar(self, binary):
    """Return the appropriate android.jar.

    :param AndroidBinary binary: AndroidBinary that requires the output of the aapt invocation.
    """
    target_sdk = self._forced_target_sdk or binary.target_sdk
    android_jar = os.path.join('platforms', 'android-' + target_sdk, 'android.jar')

    # The android.jar is bound for the classpath and so must be under the buildroot.
    return self.android_sdk.register_android_tool(android_jar, workdir=self.workdir)
