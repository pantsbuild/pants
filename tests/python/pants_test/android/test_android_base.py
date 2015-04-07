# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import textwrap
from contextlib import contextmanager

from twitter.common.collections import maybe_list

from pants.backend.android.targets.android_binary import AndroidBinary
from pants.backend.android.targets.android_library import AndroidLibrary
from pants.backend.android.targets.android_resources import AndroidResources
from pants.util.contextutil import temporary_dir, temporary_file
from pants.util.dirutil import chmod_plus_x, touch
from pants_test.tasks.task_test_base import TaskTestBase


class TestAndroidBase(TaskTestBase):
  """Base class for Android tests that provides some mock structures useful for testing."""

  @staticmethod
  def android_manifest():
    manifest = textwrap.dedent(
      """<?xml version="1.0" encoding="utf-8"?>
      <manifest xmlns:android="http://schemas.android.com/apk/res/android"
          package="org.pantsbuild.example.hello" >
          <uses-sdk
              android:minSdkVersion="8"
              android:targetSdkVersion="19" />
      </manifest>
      """)
    return manifest

  @contextmanager
  def android_binary(self, name=None, dependencies=None):
    """Represent an android_binary target."""
    with temporary_file() as fp:
      fp.write(self.android_manifest())
      fp.close()
      path = fp.name
      name = name if name else 'binary'
      deps = dependencies if dependencies else []
      target = self.make_target(spec=':{}'.format(name),
                                target_type=AndroidBinary,
                                manifest=path,
                                dependencies=deps)
      yield target

  @contextmanager
  def android_resources(self, name=None):
    """Represent an android_resources target."""
    with temporary_dir() as temp:
      with temporary_file() as fp:
        fp.write(self.android_manifest())
        fp.close()
        path = fp.name
        name = name if name else 'resources'
        target = self.make_target(spec=':{}'.format(name),
                                  target_type=AndroidResources,
                                  manifest=path,
                                  resource_dir=temp)
        yield target

  @contextmanager
  def android_library(self, name=None, dependencies=None):
    """Represent an android_library target."""
    with temporary_file() as fp:
      fp.write(self.android_manifest())
      fp.close()
      path = fp.name
      deps = dependencies if dependencies else []
      name = name if name else 'library'
      target = self.make_target(spec=':{}'.format(name),
                                target_type=AndroidLibrary,
                                manifest=path,
                                dependencies=deps)
      yield target

@contextmanager
def distribution(installed_sdks=('18', '19'),
                 installed_build_tools=('19.1.0', '20.0.0'),
                 files=('android.jar',),
                 executables=('aapt', 'zipalign')):
  """Mock Android SDK Distribution.

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
    yield sdk
