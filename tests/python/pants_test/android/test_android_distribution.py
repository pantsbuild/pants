# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
import subprocess
import unittest
from collections import namedtuple
from contextlib import contextmanager

import pytest
from twitter.common.collections import maybe_list
from twitter.common.contextutil import environment_as, temporary_dir
from twitter.common.dirutil import chmod_plus_x, safe_mkdir, safe_open, touch

from pants.backend.android.distribution import AndroidDistribution


class TestAndroidDistributionTest(unittest.TestCase):
  EXE = namedtuple('Exe', ['name', 'contents'])

  @classmethod
  def exe(cls, name):  #TODO(mateor) unused right now--use or delete
    contents = None
    return cls.EXE(name, contents=contents)

  @contextmanager
  # default for testing purposes being sdk 18 and 19, with latest build-tools 19.1.0
  def distribution(self, installed_sdks=["18", "19"], installed_build_tools=["19.1.0"],
                   files='android.jar', executables='aapt'):
    with temporary_dir() as sdk:
      for sdks in installed_sdks:
        test_aapt = touch(os.path.join(sdk, 'platforms', 'android-' + sdks, files))
      for build in installed_build_tools:
        for exe in maybe_list(executables or ()):
          path = os.path.join(sdk, 'build-tools', build, exe)
          with safe_open(path, 'w') as fp:
            fp.write('')
          chmod_plus_x(path)
      yield sdk

  def test_validate_function(self):
    with pytest.raises(TypeError):
      with self.distribution() as sdk:
        AndroidDistribution(sdk_path=sdk).validate(target_sdk='19')

    with pytest.raises(TypeError):
      with self.distribution() as sdk:
        AndroidDistribution(sdk_path=sdk).validate(build_tools_version='19.1.0')

    with self.distribution() as sdk:
      AndroidDistribution(sdk_path=sdk).validate(target_sdk="18", build_tools_version='19.1.0')

  def validate__installed_versions(self):
    with pytest.raises(AndroidDistribution.Error):
      with self.distribution() as sdk:
        AndroidDistribution(sdk_path=sdk).validate(target_sdk="20")

    with pytest.raises(AndroidDistribution.Error):
      with self.distribution() as sdk:
        AndroidDistribution(sdk_path=sdk).validate(build_tools_version="1.1.1")

    with pytest.raises(AndroidDistribution.Error):
      with self.distribution() as sdk:
        AndroidDistribution(sdk_path=sdk).validate(sdk_path="18", build_tools_version="1.1.1")

    with pytest.raises(AndroidDistribution.Error):
      with self.distribution() as sdk:
        AndroidDistribution(sdk_path=sdk).validate(sdk_path="20", build_tools_version="19.1.0")

    with self.distribution() as sdk:
      AndroidDistribution(sdk_path=sdk).validate(sdk_path="18", build_tools_version="19.1.0")


  def test_locate_tools(self):
    with self.distribution() as sdk:
      self.assertEquals(False, AndroidDistribution(sdk_path=sdk).locate_build_tools(build_tools_version="20"))

    with self.distribution() as sdk:
      self.assertEquals(False, AndroidDistribution(sdk_path=sdk).locate_build_tools(build_tools_version=""))

    with pytest.raises(TypeError):
      with self.distribution() as sdk:
        AndroidDistribution(sdk_path=sdk).locate_build_tools(target_sdk="19.1.0")

    with self.distribution() as sdk:
      self.assertEquals(True, AndroidDistribution(sdk_path=sdk).locate_build_tools(build_tools_version="19.1.0"))

  def test_locate_sdk(self):
    with self.distribution() as sdk:
      self.assertEquals(False, AndroidDistribution(sdk_path=sdk).locate_target_sdk(target_sdk="22"))

    with self.distribution() as sdk:
      self.assertEquals(False, AndroidDistribution(sdk_path=sdk).locate_target_sdk(target_sdk="1"))

    with self.distribution() as sdk:
      self.assertEquals(False, AndroidDistribution(sdk_path=sdk).locate_target_sdk(target_sdk=""))

    with self.distribution() as sdk:
      self.assertEquals(True, AndroidDistribution(sdk_path=sdk).locate_target_sdk(target_sdk="18"))

