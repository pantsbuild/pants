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
from pants.util.contextutil import temporary_dir, temporary_file
from pants.util.dirutil import chmod_plus_x, touch
from pants_test.tasks.task_test_base import TaskTestBase


class TestAndroidBase(TaskTestBase):
  """Base class for Android tests that provides some mock structures useful for testing."""

  @contextmanager
  def android_binary(self):
    """Represent an android_binary target, providing a mock version of the required manifest."""
    with temporary_file() as fp:
      fp.write(textwrap.dedent(
        """<?xml version="1.0" encoding="utf-8"?>
        <manifest xmlns:android="http://schemas.android.com/apk/res/android"
            package="org.pantsbuild.example.hello" >
            <uses-sdk
                android:minSdkVersion="8"
                android:targetSdkVersion="19" />
        </manifest>
        """))
      path = fp.name
      fp.close()
      target = self.make_target(spec=':binary',
                                target_type=AndroidBinary,
                                manifest=path)
      yield target


@contextmanager
def distribution(installed_sdks=('18', '19'),
                 installed_build_tools=('19.1.0',),
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
