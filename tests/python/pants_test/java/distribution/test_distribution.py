# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from collections import namedtuple
from contextlib import contextmanager
import os
import subprocess
import textwrap
import unittest

import pytest
from twitter.common.collections import maybe_list

from pants.base.revision import Revision
from pants.java.distribution.distribution import Distribution
from pants.util.contextutil import environment_as, temporary_dir
from pants.util.dirutil import chmod_plus_x, safe_open, touch


class MockDistributionTest(unittest.TestCase):
  EXE = namedtuple('Exe', ['name', 'contents'])


  @classmethod
  def exe(cls, name, version=None):
    contents = None if not version else textwrap.dedent('''
        #!/bin/sh
        if [ $# -ne 3 ]; then
          # Sanity check a classpath switch with a value plus the classname for main
          echo "Expected 3 arguments, got $#: $@" >&2
          exit 1
        fi
        echo "java.version=%s"
      ''' % version).strip()
    return cls.EXE(name, contents=contents)

  @contextmanager
  def env(self, **kwargs):
    environment = dict(JDK_HOME=None, JAVA_HOME=None, PATH=None)
    environment.update(**kwargs)
    with environment_as(**environment):
      yield

  @contextmanager
  def distribution(self, files=None, executables=None):
    with temporary_dir() as jdk:
      for f in maybe_list(files or ()):
        touch(os.path.join(jdk, f))
      for exe in maybe_list(executables or (), expected_type=self.EXE):
        path = os.path.join(jdk, exe.name)
        with safe_open(path, 'w') as fp:
          fp.write(exe.contents or '')
        chmod_plus_x(path)
      yield jdk

  def setUp(self):
    super(MockDistributionTest, self).setUp()
    # Save local cache and then flush so tests get a clean environment. _CACHE restored in tearDown.
    self._local_cache = Distribution._CACHE
    Distribution._CACHE = {}

  def tearDown(self):
    super(MockDistributionTest, self).tearDown()
    Distribution._CACHE = self._local_cache

  def test_validate_basic(self):
    with pytest.raises(Distribution.Error):
      with self.distribution() as jdk:
        Distribution(bin_path=jdk).validate()

    with pytest.raises(Distribution.Error):
      with self.distribution(files='java') as jdk:
        Distribution(bin_path=jdk).validate()

    with self.distribution(executables=self.exe('java')) as jdk:
      Distribution(bin_path=jdk).validate()

  def test_validate_jdk(self):
    with pytest.raises(Distribution.Error):
      with self.distribution(executables=self.exe('java')) as jdk:
        Distribution(bin_path=jdk, jdk=True).validate()

    with self.distribution(executables=[self.exe('java'), self.exe('javac')]) as jdk:
      Distribution(bin_path=jdk, jdk=True).validate()

  def test_validate_version(self):
    with pytest.raises(Distribution.Error):
      with self.distribution(executables=self.exe('java', '1.7.0_25')) as jdk:
        Distribution(bin_path=jdk, minimum_version='1.7.0_45').validate()
    with pytest.raises(Distribution.Error):
      with self.distribution(executables=self.exe('java', '1.8.0_1')) as jdk:
        Distribution(bin_path=jdk, maximum_version='1.7.9999').validate()

    with self.distribution(executables=self.exe('java', '1.7.0_25')) as jdk:
      Distribution(bin_path=jdk, minimum_version='1.7.0_25').validate()
      Distribution(bin_path=jdk, minimum_version=Revision.semver('1.6.0')).validate()
      Distribution(bin_path=jdk, minimum_version='1.7.0_25', maximum_version='1.7.999').validate()

  def test_validated_binary(self):
    with pytest.raises(Distribution.Error):
      with self.distribution(files='jar', executables=self.exe('java')) as jdk:
        Distribution(bin_path=jdk).binary('jar')

    with self.distribution(executables=[self.exe('java'), self.exe('jar')]) as jdk:
      Distribution(bin_path=jdk).binary('jar')

  def test_locate(self):

    with pytest.raises(Distribution.Error):
      with self.env():
        Distribution.locate()

    with pytest.raises(Distribution.Error):
      with self.distribution(files='java') as jdk:
        with self.env(PATH=jdk):
          Distribution.locate()

    with pytest.raises(Distribution.Error):
      with self.distribution(executables=self.exe('java')) as jdk:
        with self.env(PATH=jdk):
          Distribution.locate(jdk=True)

    with pytest.raises(Distribution.Error):
      with self.distribution(executables=self.exe('java', '1.6.0')) as jdk:
        with self.env(PATH=jdk):
          Distribution.locate(minimum_version='1.7.0')

    with pytest.raises(Distribution.Error):
      with self.distribution(executables=self.exe('java', '1.8.0')) as jdk:
        with self.env(PATH=jdk):
          Distribution.locate(maximum_version='1.7.999')

    with pytest.raises(Distribution.Error):
      with self.distribution(executables=self.exe('java')) as jdk:
        with self.env(JDK_HOME=jdk):
          Distribution.locate()

    with pytest.raises(Distribution.Error):
      with self.distribution(executables=self.exe('java')) as jdk:
        with self.env(JAVA_HOME=jdk):
          Distribution.locate()

    with self.distribution(executables=self.exe('java')) as jdk:
      with self.env(PATH=jdk):
        Distribution.locate()

    with self.distribution(executables=[self.exe('java'), self.exe('javac')]) as jdk:
      with self.env(PATH=jdk):
        Distribution.locate(jdk=True)

    with self.distribution(executables=self.exe('java', '1.7.0')) as jdk:
      with self.env(PATH=jdk):
        Distribution.locate(minimum_version='1.6.0')
      with self.env(PATH=jdk):
        Distribution.locate(maximum_version='1.7.999')
      with self.env(PATH=jdk):
        Distribution.locate(minimum_version='1.6.0', maximum_version='1.7.999')

    with self.distribution(executables=self.exe('bin/java')) as jdk:
      with self.env(JDK_HOME=jdk):
        Distribution.locate()

    with self.distribution(executables=self.exe('bin/java')) as jdk:
      with self.env(JAVA_HOME=jdk):
        Distribution.locate()

  def test_cached_good_min(self):
    with self.distribution(executables=self.exe('java', '1.7.0_33')) as jdk:
      with self.env(PATH=jdk):
        Distribution.cached(minimum_version='1.7.0_25')

  def test_cached_good_max(self):
    with self.distribution(executables=self.exe('java', '1.7.0_33')) as jdk:
      with self.env(PATH=jdk):
        Distribution.cached(maximum_version='1.7.0_50')

  def test_cached_good_bounds(self):
    with self.distribution(executables=self.exe('java', '1.7.0_33')) as jdk:
      with self.env(PATH=jdk):
        Distribution.cached(minimum_version='1.6.0_35', maximum_version='1.7.0_55')

  def test_cached_too_low(self):
    with self.distribution(executables=self.exe('java', '1.7.0_33')) as jdk:
      with self.env(PATH=jdk):
        with self.assertRaises(Distribution.Error):
          Distribution.cached(minimum_version='1.7.0_40')

  def test_cached_too_high(self):
    with self.distribution(executables=self.exe('java', '1.7.0_83')) as jdk:
      with self.env(PATH=jdk):
        with self.assertRaises(Distribution.Error):
          Distribution.cached(maximum_version='1.7.0_55')

  def test_cached_low_fault(self):
    with self.distribution(executables=self.exe('java', '1.7.0_33')) as jdk:
      with self.env(PATH=jdk):
        with self.assertRaises(Distribution.Error):
          Distribution.cached(minimum_version='1.7.0_35', maximum_version='1.7.0_55')

  def test_cached_high_fault(self):
    with self.distribution(executables=self.exe('java', '1.7.0_33')) as jdk:
      with self.env(PATH=jdk):
        with self.assertRaises(Distribution.Error):
          Distribution.cached(minimum_version='1.6.0_00', maximum_version='1.6.0_50')

  def test_cached_conflicting(self):
    with self.distribution(executables=self.exe('java', '1.7.0_33')) as jdk:
      with self.env(PATH=jdk):
        with self.assertRaises(Distribution.Error):
          Distribution.cached(minimum_version='1.7.0_00', maximum_version='1.6.0_50')

  def test_cached_bad_input(self):
    with self.assertRaises(ValueError):
      with self.distribution(executables=self.exe('java', '1.7.0_33')) as jdk:
        with self.env(PATH=jdk):
          Distribution.cached(minimum_version=1.7, maximum_version=1.8)

def exe_path(name):
  process = subprocess.Popen(['which', name], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
  stdout, _ = process.communicate()
  if process.returncode != 0:
    return None
  path = stdout.strip()
  return path if os.path.exists(path) and os.access(path, os.X_OK) else None


class LiveDistributionTest(unittest.TestCase):
  JAVA = exe_path('java')
  JAVAC = exe_path('javac')

  @pytest.mark.skipif('not LiveDistributionTest.JAVA', reason='No java executable on the PATH.')
  def test_validate_live(self):
    with pytest.raises(Distribution.Error):
      Distribution(bin_path=os.path.dirname(self.JAVA), minimum_version='999.9.9').validate()
    with pytest.raises(Distribution.Error):
      Distribution(bin_path=os.path.dirname(self.JAVA), maximum_version='0.0.1').validate()

    Distribution(bin_path=os.path.dirname(self.JAVA)).validate()
    Distribution(bin_path=os.path.dirname(self.JAVA), minimum_version='1.3.1').validate()
    Distribution(bin_path=os.path.dirname(self.JAVA), maximum_version='999.999.999').validate()
    Distribution(bin_path=os.path.dirname(self.JAVA), minimum_version='1.3.1',
                 maximum_version='999.999.999').validate()
    Distribution.locate(jdk=False)

  @pytest.mark.skipif('not LiveDistributionTest.JAVAC', reason='No javac executable on the PATH.')
  def test_validate_live_jdk(self):
    Distribution(bin_path=os.path.dirname(self.JAVAC), jdk=True).validate()
    Distribution(bin_path=os.path.dirname(self.JAVAC), jdk=True).binary('javap')
    Distribution.locate(jdk=True)
