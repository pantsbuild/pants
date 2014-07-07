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
from twitter.common.dirutil import chmod_plus_x, safe_open, touch

from pants.backend.android.distribution import AndroidDistribution


class TestAndroidDistributionTest(unittest.TestCase):
  EXE = namedtuple('Exe', ['name', 'contents'])

  @classmethod
  def exe(cls, name):
    contents = None
    return cls.EXE(name, contents=contents)

  @contextmanager
  def distribution(self, files=None, executables=None):
    with temporary_dir() as sdk:
      for f in maybe_list(files or ()):
        touch(os.path.join(sdk, f))
      for exe in maybe_list(executables or ()):
        path = os.path.join(path, exe.name)
        with safe_open(path, 'w') as fp:
          fp.write(exe.contents or '')
        chmod_plus_x(path)
      yield sdk

  def test_args(self):
    with pytest.raises(TypeError):
      with self.distribution() as sdk:
        AndroidDistribution(sdk_path=sdk).validate(target_sdk='19')

    with pytest.raises(TypeError):
      with self.distribution() as sdk:
        AndroidDistribution(sdk_path=sdk).validate(build_tools_version='19.1.0')

    with self.distribution(files='platforms/android-18/android.jar') as jdk:
      AndroidDistribution(sdk_path=sdk).validate(target_sdk="18", build_tools_version='19.1.0')
        # assertEquals aapt_tool and os.path.join ETC