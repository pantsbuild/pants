# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import textwrap
from contextlib import contextmanager

from pants.util.contextutil import temporary_dir, temporary_file
from pants.util.dirutil import chmod_plus_x, touch
from pants_test.jvm.jvm_tool_task_test_base import JvmToolTaskTestBase
from twitter.common.collections import maybe_list

from pants.contrib.android.targets.android_binary import AndroidBinary
from pants.contrib.android.targets.android_library import AndroidLibrary
from pants.contrib.android.targets.android_resources import AndroidResources
from pants.contrib.android.targets.android_target import AndroidTarget


class TestAndroidBase(JvmToolTaskTestBase):
  """Base class for Android tests that provides some mock structures useful for testing.

    :API: public
  """

  @staticmethod
  def android_manifest(package_name=None, target_sdk=None):
    """
    :API: public
    """
    package_name = package_name or 'org.pantsbuild.example.hello'
    sdk = target_sdk or 19
    manifest = textwrap.dedent(
      """<?xml version="1.0" encoding="utf-8"?>
      <manifest xmlns:android="http://schemas.android.com/apk/res/android"
          package="{}" >
          <uses-sdk
              android:minSdkVersion="8"
              android:targetSdkVersion="{}" />
      </manifest>
      """.format(package_name, sdk))
    return manifest

  @contextmanager
  def android_target(self, target_name=None, package_name=None, target_sdk=None, dependencies=None,
                     target_type=AndroidTarget, **kwargs):
    """Represent an Android target.

    :API: public
    """
    with temporary_file() as manifest:
      manifest.write(self.android_manifest(package_name=package_name, target_sdk=target_sdk))
      manifest.close()
      target_name = target_name or 'target'
      deps = dependencies or []
      target = self.make_target(spec=':{}'.format(target_name),
                                target_type=target_type,
                                manifest=manifest.name,
                                dependencies=deps,
                                **kwargs)
      yield target

  @contextmanager
  def android_binary(self, target_name=None, dependencies=None, package_name=None, target_sdk=None):
    """Represent an android_binary target.

    :API: public
    """
    with self.android_target(target_name=target_name or 'binary',
                             dependencies=dependencies,
                             package_name=package_name,
                             target_sdk=target_sdk,
                             target_type=AndroidBinary) as binary:
      yield binary

  @contextmanager
  def android_resources(self, target_name=None, dependencies=None, package_name=None):
    """Represent an android_resources target.

    :API: public
    """
    with temporary_dir() as temp:
      with self.android_target(target_name=target_name or 'resources',
                               dependencies=dependencies,
                               resource_dir=temp,
                               package_name=package_name,
                               target_type=AndroidResources) as resources:
        yield resources

  @contextmanager
  def android_library(self, target_name=None, libraries=None, include_patterns=None,
                      exclude_patterns=None, dependencies=None, package_name=None):
    """Represent an android_library target.

    :API: public
    """
    with self.android_target(target_name=target_name or 'library',
                             libraries=libraries,
                             include_patterns=include_patterns,
                             exclude_patterns=exclude_patterns,
                             dependencies=dependencies,
                             package_name=package_name,
                             target_type=AndroidLibrary) as library:
      yield library


@contextmanager
def distribution(installed_sdks=('18', '19'),
                 installed_build_tools=('19.1.0', '20.0.0'),
                 files=('android.jar',),
                 executables=('aapt', 'zipalign')):
  """Mock Android SDK Distribution.

  :API: public

  :param tuple[strings] installed_sdks: SDK versions of the files being mocked.
  :param tuple[strings] installed_build_tools: Build tools version of any tools.
  :param tuple[strings] files: The files are to mock non-executables and one will be created for
    each installed_sdks version.
  :param tuple[strings] executables: Executables are any required tools and one is created for
    each installed_build_tools version.
  """
  with temporary_dir() as sdk:
    for sdk_version in installed_sdks:
      for android_file in files:
        touch(os.path.join(sdk, 'platforms', 'android-' + sdk_version, android_file))
    for version in installed_build_tools:
      for exe in maybe_list(executables or ()):
        path = os.path.join(sdk, 'build-tools', version, exe)
        touch(path)
        chmod_plus_x(path)
      dx_path = os.path.join(sdk, 'build-tools', version, 'lib/dx.jar')
      touch(dx_path)
    yield sdk
