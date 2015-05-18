# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import subprocess
import textwrap
import unittest
from collections import namedtuple
from contextlib import contextmanager

from twitter.common.collections import maybe_list

from pants.base.revision import Revision
from pants.java.distribution.distribution import Distribution
from pants.util.contextutil import environment_as, temporary_dir
from pants.util.dirutil import chmod_plus_x, safe_open, touch


class MockDistributionTest(unittest.TestCase):
  EXE = namedtuple('Exe', ['relpath', 'contents'])

  @classmethod
  def exe(cls, relpath, version=None):
    contents = textwrap.dedent("""
        #!/bin/sh
        if [ $# -ne 3 ]; then
          # Sanity check a classpath switch with a value plus the classname for main
          echo "Expected 3 arguments, got $#: $@" >&2
          exit 1
        fi
        echo "java.home=${{DIST_ROOT}}"
        {}
      """.format('echo "java.version={}"'.format(version) if version else '')).strip()
    return cls.EXE(relpath, contents=contents)

  @contextmanager
  def env(self, **kwargs):
    environment = dict(JDK_HOME=None, JAVA_HOME=None, PATH=None)
    environment.update(**kwargs)
    with environment_as(**environment):
      yield

  @contextmanager
  def distribution(self, files=None, executables=None, java_home=None):
    with temporary_dir() as dist_root:
      with environment_as(DIST_ROOT=os.path.join(dist_root, java_home) if java_home else dist_root):
        for f in maybe_list(files or ()):
          touch(os.path.join(dist_root, f))
        for exe in maybe_list(executables or (), expected_type=self.EXE):
          path = os.path.join(dist_root, exe.relpath)
          with safe_open(path, 'w') as fp:
            fp.write(exe.contents or '')
          chmod_plus_x(path)
        yield dist_root

  def setUp(self):
    super(MockDistributionTest, self).setUp()
    # Save local cache and then flush so tests get a clean environment. _CACHE restored in tearDown.
    self._local_cache = Distribution._CACHE
    Distribution._CACHE = {}

  def tearDown(self):
    super(MockDistributionTest, self).tearDown()
    Distribution._CACHE = self._local_cache

  def test_validate_basic(self):
    with self.assertRaises(ValueError):
      with self.distribution() as dist_root:
        Distribution(bin_path=os.path.join(dist_root, 'bin')).validate()

    with self.assertRaises(Distribution.Error):
      with self.distribution(files='bin/java') as dist_root:
        Distribution(bin_path=os.path.join(dist_root, 'bin')).validate()

    with self.distribution(executables=self.exe('bin/java')) as dist_root:
      Distribution(bin_path=os.path.join(dist_root, 'bin')).validate()

  def test_validate_jre(self):
    with self.distribution(executables=self.exe('bin/java')) as dist_root:
      Distribution(bin_path=os.path.join(dist_root, 'bin'), jdk=False).validate()

  def test_validate_jdk(self):
    with self.assertRaises(Distribution.Error):
      with self.distribution(executables=self.exe('bin/java')) as dist_root:
        Distribution(bin_path=os.path.join(dist_root, 'bin'), jdk=True).validate()

    with self.distribution(executables=[self.exe('bin/java'), self.exe('bin/javac')]) as dist_root:
      Distribution(bin_path=os.path.join(dist_root, 'bin'), jdk=True).validate()

    with self.distribution(executables=[self.exe('jre/bin/java'),
                                        self.exe('bin/javac')],
                           java_home='jre') as dist_root:
      Distribution(bin_path=os.path.join(dist_root, 'jre/bin'), jdk=True).validate()

  def test_validate_version(self):
    with self.assertRaises(Distribution.Error):
      with self.distribution(executables=self.exe('bin/java', '1.7.0_25')) as dist_root:
        Distribution(bin_path=os.path.join(dist_root, 'bin'), minimum_version='1.7.0_45').validate()
    with self.assertRaises(Distribution.Error):
      with self.distribution(executables=self.exe('bin/java', '1.8.0_1')) as dist_root:
        Distribution(bin_path=os.path.join(dist_root, 'bin'), maximum_version='1.7.9999').validate()

    with self.distribution(executables=self.exe('bin/java', '1.7.0_25')) as dist_root:
      Distribution(bin_path=os.path.join(dist_root, 'bin'), minimum_version='1.7.0_25').validate()
      Distribution(bin_path=os.path.join(dist_root, 'bin'),
                   minimum_version=Revision.semver('1.6.0')).validate()
      Distribution(bin_path=os.path.join(dist_root, 'bin'),
                   minimum_version='1.7.0_25',
                   maximum_version='1.7.999').validate()

  def test_validated_binary(self):
    with self.assertRaises(Distribution.Error):
      with self.distribution(files='bin/jar', executables=self.exe('bin/java')) as dist_root:
        Distribution(bin_path=os.path.join(dist_root, 'bin')).binary('jar')

    with self.distribution(executables=[self.exe('bin/java'), self.exe('bin/jar')]) as dist_root:
      Distribution(bin_path=os.path.join(dist_root, 'bin')).binary('jar')

    with self.assertRaises(Distribution.Error):
      with self.distribution(executables=[self.exe('jre/bin/java'),
                                          self.exe('bin/jar')],
                             java_home='jre') as dist_root:
        Distribution(bin_path=os.path.join(dist_root, 'jre', 'bin')).binary('jar')

    with self.distribution(executables=[self.exe('jre/bin/java'),
                                        self.exe('bin/jar'),
                                        self.exe('bin/javac')],
                           java_home='jre') as dist_root:
      Distribution(bin_path=os.path.join(dist_root, 'jre', 'bin')).binary('jar')

    with self.distribution(executables=[self.exe('jre/bin/java'),
                                        self.exe('jre/bin/java_vm'),
                                        self.exe('bin/javac')],
                           java_home='jre') as dist_root:
      Distribution(bin_path=os.path.join(dist_root, 'jre', 'bin')).binary('java_vm')

  def test_validated_library(self):
    with self.assertRaises(Distribution.Error):
      with self.distribution(executables=self.exe('bin/java')) as dist_root:
        Distribution(bin_path=os.path.join(dist_root, 'bin')).find_libs(['tools.jar'])

    with self.distribution(executables=self.exe('bin/java'), files='lib/tools.jar') as dist_root:
      distribution = Distribution(bin_path=os.path.join(dist_root, 'bin'))
      self.assertEqual([os.path.join(dist_root, 'lib', 'tools.jar')],
                       distribution.find_libs(['tools.jar']))

    with self.distribution(executables=[self.exe('jre/bin/java'), self.exe('bin/javac')],
                           files=['lib/tools.jar', 'jre/lib/rt.jar'],
                           java_home='jre') as dist_root:
      distribution = Distribution(bin_path=os.path.join(dist_root, 'jre/bin'))
      self.assertEqual([os.path.join(dist_root, 'lib', 'tools.jar'),
                        os.path.join(dist_root, 'jre', 'lib', 'rt.jar')],
                       distribution.find_libs(['tools.jar', 'rt.jar']))

  def test_locate(self):
    with self.assertRaises(Distribution.Error):
      with self.env():
        Distribution.locate()

    with self.assertRaises(Distribution.Error):
      with self.distribution(files='bin/java') as dist_root:
        with self.env(PATH=os.path.join(dist_root, 'bin')):
          Distribution.locate()

    with self.assertRaises(Distribution.Error):
      with self.distribution(executables=self.exe('bin/java')) as dist_root:
        with self.env(PATH=os.path.join(dist_root, 'bin')):
          Distribution.locate(jdk=True)

    with self.assertRaises(Distribution.Error):
      with self.distribution(executables=self.exe('bin/java', '1.6.0')) as dist_root:
        with self.env(PATH=os.path.join(dist_root, 'bin')):
          Distribution.locate(minimum_version='1.7.0')

    with self.assertRaises(Distribution.Error):
      with self.distribution(executables=self.exe('bin/java', '1.8.0')) as dist_root:
        with self.env(PATH=os.path.join(dist_root, 'bin')):
          Distribution.locate(maximum_version='1.7.999')

    with self.assertRaises(Distribution.Error):
      with self.distribution(executables=self.exe('java')) as dist_root:
        with self.env(JDK_HOME=dist_root):
          Distribution.locate()

    with self.assertRaises(Distribution.Error):
      with self.distribution(executables=self.exe('java')) as dist_root:
        with self.env(JAVA_HOME=dist_root):
          Distribution.locate()

    with self.distribution(executables=self.exe('bin/java')) as dist_root:
      with self.env(PATH=os.path.join(dist_root, 'bin')):
        Distribution.locate()

    with self.distribution(executables=[self.exe('bin/java'), self.exe('bin/javac')]) as dist_root:
      with self.env(PATH=os.path.join(dist_root, 'bin')):
        Distribution.locate(jdk=True)

    with self.distribution(executables=[self.exe('jre/bin/java'),
                                        self.exe('bin/javac')],
                           java_home='jre') as dist_root:
      with self.env(PATH=os.path.join(dist_root, 'jre', 'bin')):
        Distribution.locate(jdk=True)

    with self.distribution(executables=self.exe('bin/java', '1.7.0')) as dist_root:
      with self.env(PATH=os.path.join(dist_root, 'bin')):
        Distribution.locate(minimum_version='1.6.0')
      with self.env(PATH=os.path.join(dist_root, 'bin')):
        Distribution.locate(maximum_version='1.7.999')
      with self.env(PATH=os.path.join(dist_root, 'bin')):
        Distribution.locate(minimum_version='1.6.0', maximum_version='1.7.999')

    with self.distribution(executables=self.exe('bin/java')) as dist_root:
      with self.env(JDK_HOME=dist_root):
        Distribution.locate()

    with self.distribution(executables=self.exe('bin/java')) as dist_root:
      with self.env(JAVA_HOME=dist_root):
        Distribution.locate()

  def test_cached_good_min(self):
    with self.distribution(executables=self.exe('bin/java', '1.7.0_33')) as dist_root:
      with self.env(PATH=os.path.join(dist_root, 'bin')):
        Distribution.cached(minimum_version='1.7.0_25')

  def test_cached_good_max(self):
    with self.distribution(executables=self.exe('bin/java', '1.7.0_33')) as dist_root:
      with self.env(PATH=os.path.join(dist_root, 'bin')):
        Distribution.cached(maximum_version='1.7.0_50')

  def test_cached_good_bounds(self):
    with self.distribution(executables=self.exe('bin/java', '1.7.0_33')) as dist_root:
      with self.env(PATH=os.path.join(dist_root, 'bin')):
        Distribution.cached(minimum_version='1.6.0_35', maximum_version='1.7.0_55')

  def test_cached_too_low(self):
    with self.distribution(executables=self.exe('bin/java', '1.7.0_33')) as dist_root:
      with self.env(PATH=os.path.join(dist_root, 'bin')):
        with self.assertRaises(Distribution.Error):
          Distribution.cached(minimum_version='1.7.0_40')

  def test_cached_too_high(self):
    with self.distribution(executables=self.exe('bin/java', '1.7.0_83')) as dist_root:
      with self.env(PATH=os.path.join(dist_root, 'bin')):
        with self.assertRaises(Distribution.Error):
          Distribution.cached(maximum_version='1.7.0_55')

  def test_cached_low_fault(self):
    with self.distribution(executables=self.exe('bin/java', '1.7.0_33')) as dist_root:
      with self.env(PATH=os.path.join(dist_root, 'bin')):
        with self.assertRaises(Distribution.Error):
          Distribution.cached(minimum_version='1.7.0_35', maximum_version='1.7.0_55')

  def test_cached_high_fault(self):
    with self.distribution(executables=self.exe('bin/java', '1.7.0_33')) as dist_root:
      with self.env(PATH=os.path.join(dist_root, 'bin')):
        with self.assertRaises(Distribution.Error):
          Distribution.cached(minimum_version='1.6.0_00', maximum_version='1.6.0_50')

  def test_cached_conflicting(self):
    with self.distribution(executables=self.exe('bin/java', '1.7.0_33')) as dist_root:
      with self.env(PATH=os.path.join(dist_root, 'bin')):
        with self.assertRaises(Distribution.Error):
          Distribution.cached(minimum_version='1.7.0_00', maximum_version='1.6.0_50')

  def test_cached_bad_input(self):
    with self.assertRaises(ValueError):
      with self.distribution(executables=self.exe('bin/java', '1.7.0_33')) as dist_root:
        with self.env(PATH=os.path.join(dist_root, 'bin')):
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

  @unittest.skipIf(not JAVA, reason='No java executable on the PATH.')
  def test_validate_live(self):
    with self.assertRaises(Distribution.Error):
      Distribution(bin_path=os.path.dirname(self.JAVA), minimum_version='999.9.9').validate()
    with self.assertRaises(Distribution.Error):
      Distribution(bin_path=os.path.dirname(self.JAVA), maximum_version='0.0.1').validate()

    Distribution(bin_path=os.path.dirname(self.JAVA)).validate()
    Distribution(bin_path=os.path.dirname(self.JAVA), minimum_version='1.3.1').validate()
    Distribution(bin_path=os.path.dirname(self.JAVA), maximum_version='999.999.999').validate()
    Distribution(bin_path=os.path.dirname(self.JAVA), minimum_version='1.3.1',
                 maximum_version='999.999.999').validate()
    Distribution.locate(jdk=False)

  @unittest.skipIf(not JAVAC, reason='No javac executable on the PATH.')
  def test_validate_live_jdk(self):
    Distribution(bin_path=os.path.dirname(self.JAVAC), jdk=True).validate()
    Distribution(bin_path=os.path.dirname(self.JAVAC), jdk=True).binary('javap')
    Distribution.locate(jdk=True)
