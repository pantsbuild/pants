# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import subprocess
import tempfile
import textwrap
import unittest
from collections import namedtuple
from contextlib import contextmanager

from twitter.common.collections import maybe_list

from pants.base.revision import Revision
from pants.java.distribution.distribution import Distribution, DistributionLocator
from pants.util.contextutil import environment_as, temporary_dir
from pants.util.dirutil import chmod_plus_x, safe_open, safe_rmtree, touch
from pants_test.subsystem.subsystem_util import subsystem_instance


EXE = namedtuple('Exe', ['relpath', 'contents'])


def exe(relpath, version=None):
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
  return EXE(relpath, contents=contents)


@contextmanager
def distribution(files=None, executables=None, java_home=None):
  with subsystem_instance(DistributionLocator):
    with temporary_dir() as dist_root:
      with environment_as(DIST_ROOT=os.path.join(dist_root, java_home) if java_home else dist_root):
        for f in maybe_list(files or ()):
          touch(os.path.join(dist_root, f))
        for executable in maybe_list(executables or (), expected_type=EXE):
          path = os.path.join(dist_root, executable.relpath)
          with safe_open(path, 'w') as fp:
            fp.write(executable.contents or '')
          chmod_plus_x(path)
        yield dist_root


@contextmanager
def env(**kwargs):
  environment = dict(JDK_HOME=None, JAVA_HOME=None, PATH=None)
  environment.update(**kwargs)
  with environment_as(**environment):
    yield


class DistributionValidationTest(unittest.TestCase):
  def test_validate_basic(self):
    with distribution() as dist_root:
      with self.assertRaises(ValueError):
        Distribution(bin_path=os.path.join(dist_root, 'bin')).validate()

    with distribution(files='bin/java') as dist_root:
      with self.assertRaises(Distribution.Error):
        Distribution(bin_path=os.path.join(dist_root, 'bin')).validate()

    with distribution(executables=exe('bin/java')) as dist_root:
      Distribution(bin_path=os.path.join(dist_root, 'bin')).validate()

  def test_validate_jre(self):
    with distribution(executables=exe('bin/java')) as dist_root:
      Distribution(bin_path=os.path.join(dist_root, 'bin'), jdk=False).validate()

  def test_validate_jdk(self):
    with distribution(executables=exe('bin/java')) as dist_root:
      with self.assertRaises(Distribution.Error):
        Distribution(bin_path=os.path.join(dist_root, 'bin'), jdk=True).validate()

    with distribution(executables=[exe('bin/java'), exe('bin/javac')]) as dist_root:
      Distribution(bin_path=os.path.join(dist_root, 'bin'), jdk=True).validate()

    with distribution(executables=[exe('jre/bin/java'), exe('bin/javac')],
                      java_home='jre') as dist_root:
      Distribution(bin_path=os.path.join(dist_root, 'jre/bin'), jdk=True).validate()

  def test_validate_version(self):
    with distribution(executables=exe('bin/java', '1.7.0_25')) as dist_root:
      with self.assertRaises(Distribution.Error):
        Distribution(bin_path=os.path.join(dist_root, 'bin'), minimum_version='1.7.0_45').validate()
    with distribution(executables=exe('bin/java', '1.8.0_1')) as dist_root:
      with self.assertRaises(Distribution.Error):
        Distribution(bin_path=os.path.join(dist_root, 'bin'), maximum_version='1.8').validate()

    with distribution(executables=exe('bin/java', '1.7.0_25')) as dist_root:
      Distribution(bin_path=os.path.join(dist_root, 'bin'), minimum_version='1.7.0_25').validate()
      Distribution(bin_path=os.path.join(dist_root, 'bin'),
                   minimum_version=Revision.lenient('1.6')).validate()
      Distribution(bin_path=os.path.join(dist_root, 'bin'),
                   minimum_version='1.7.0_25',
                   maximum_version='1.7.999').validate()

  def test_validated_binary(self):
    with distribution(files='bin/jar', executables=exe('bin/java')) as dist_root:
      with self.assertRaises(Distribution.Error):
        Distribution(bin_path=os.path.join(dist_root, 'bin')).binary('jar')

    with distribution(executables=[exe('bin/java'), exe('bin/jar')]) as dist_root:
      Distribution(bin_path=os.path.join(dist_root, 'bin')).binary('jar')

    with distribution(executables=[exe('jre/bin/java'), exe('bin/jar')],
                      java_home='jre') as dist_root:
      with self.assertRaises(Distribution.Error):
        Distribution(bin_path=os.path.join(dist_root, 'jre', 'bin')).binary('jar')

    with distribution(executables=[exe('jre/bin/java'), exe('bin/jar'), exe('bin/javac')],
                      java_home='jre') as dist_root:
      Distribution(bin_path=os.path.join(dist_root, 'jre', 'bin')).binary('jar')

    with distribution(executables=[exe('jre/bin/java'), exe('jre/bin/java_vm'), exe('bin/javac')],
                      java_home='jre') as dist_root:
      Distribution(bin_path=os.path.join(dist_root, 'jre', 'bin')).binary('java_vm')

  def test_validated_library(self):
    with distribution(executables=exe('bin/java')) as dist_root:
      with self.assertRaises(Distribution.Error):
        Distribution(bin_path=os.path.join(dist_root, 'bin')).find_libs(['tools.jar'])

    with distribution(executables=exe('bin/java'), files='lib/tools.jar') as dist_root:
      dist = Distribution(bin_path=os.path.join(dist_root, 'bin'))
      self.assertEqual([os.path.join(dist_root, 'lib', 'tools.jar')],
                       dist.find_libs(['tools.jar']))

    with distribution(executables=[exe('jre/bin/java'), exe('bin/javac')],
                      files=['lib/tools.jar', 'jre/lib/rt.jar'],
                      java_home='jre') as dist_root:
      dist = Distribution(bin_path=os.path.join(dist_root, 'jre/bin'))
      self.assertEqual([os.path.join(dist_root, 'lib', 'tools.jar'),
                        os.path.join(dist_root, 'jre', 'lib', 'rt.jar')],
                       dist.find_libs(['tools.jar', 'rt.jar']))


class BaseDistributionLocationTest(unittest.TestCase):
  def make_tmp_dir(self):
    tmpdir = tempfile.mkdtemp()
    self.addCleanup(safe_rmtree, tmpdir)
    return tmpdir

  def set_up_no_linux_discovery(self):
    orig_java_dist_dir = DistributionLocator._JAVA_DIST_DIR

    def restore_java_dist_dir():
      DistributionLocator._JAVA_DIST_DIR = orig_java_dist_dir
    DistributionLocator._JAVA_DIST_DIR = self.make_tmp_dir()
    self.addCleanup(restore_java_dist_dir)

  def set_up_no_osx_discovery(self):
    osx_java_home_exe = DistributionLocator._OSX_JAVA_HOME_EXE

    def restore_osx_java_home_exe():
      DistributionLocator._OSX_JAVA_HOME_EXE = osx_java_home_exe
    DistributionLocator._OSX_JAVA_HOME_EXE = os.path.join(self.make_tmp_dir(), 'java_home')
    self.addCleanup(restore_osx_java_home_exe)


class BaseDistributionLocationEnvOnlyTest(BaseDistributionLocationTest):
  def setUp(self):
    self.set_up_no_linux_discovery()
    self.set_up_no_osx_discovery()


class DistributionEnvLocationTest(BaseDistributionLocationEnvOnlyTest):
  def test_locate_none(self):
    with env():
      with self.assertRaises(Distribution.Error):
        with subsystem_instance(DistributionLocator):
          DistributionLocator.locate()

  def test_locate_java_not_executable(self):
    with distribution(files='bin/java') as dist_root:
      with env(PATH=os.path.join(dist_root, 'bin')):
        with self.assertRaises(Distribution.Error):
          DistributionLocator.locate()

  def test_locate_jdk_is_jre(self):
    with distribution(executables=exe('bin/java')) as dist_root:
      with env(PATH=os.path.join(dist_root, 'bin')):
        with self.assertRaises(Distribution.Error):
          DistributionLocator.locate(jdk=True)

  def test_locate_version_to_low(self):
    with distribution(executables=exe('bin/java', '1.6.0')) as dist_root:
      with env(PATH=os.path.join(dist_root, 'bin')):
        with self.assertRaises(Distribution.Error):
          DistributionLocator.locate(minimum_version='1.7.0')

  def test_locate_version_to_high(self):
    with distribution(executables=exe('bin/java', '1.8.0')) as dist_root:
      with env(PATH=os.path.join(dist_root, 'bin')):
        with self.assertRaises(Distribution.Error):
          DistributionLocator.locate(maximum_version='1.7.999')

  def test_locate_invalid_jdk_home(self):
    with distribution(executables=exe('java')) as dist_root:
      with env(JDK_HOME=dist_root):
        with self.assertRaises(Distribution.Error):
          DistributionLocator.locate()

  def test_locate_invalid_java_home(self):
    with distribution(executables=exe('java')) as dist_root:
      with env(JAVA_HOME=dist_root):
        with self.assertRaises(Distribution.Error):
          DistributionLocator.locate()

  def test_locate_jre_by_path(self):
    with distribution(executables=exe('bin/java')) as dist_root:
      with env(PATH=os.path.join(dist_root, 'bin')):
        DistributionLocator.locate()

  def test_locate_jdk_by_path(self):
    with distribution(executables=[exe('bin/java'), exe('bin/javac')]) as dist_root:
      with env(PATH=os.path.join(dist_root, 'bin')):
        DistributionLocator.locate(jdk=True)

  def test_locate_jdk_via_jre_path(self):
    with distribution(executables=[exe('jre/bin/java'), exe('bin/javac')],
                      java_home='jre') as dist_root:
      with env(PATH=os.path.join(dist_root, 'jre', 'bin')):
        DistributionLocator.locate(jdk=True)

  def test_locate_version_greater_then_or_equal(self):
    with distribution(executables=exe('bin/java', '1.7.0')) as dist_root:
      with env(PATH=os.path.join(dist_root, 'bin')):
        DistributionLocator.locate(minimum_version='1.6.0')

  def test_locate_version_less_then_or_equal(self):
    with distribution(executables=exe('bin/java', '1.7.0')) as dist_root:
      with env(PATH=os.path.join(dist_root, 'bin')):
        DistributionLocator.locate(maximum_version='1.7.999')

  def test_locate_version_within_range(self):
    with distribution(executables=exe('bin/java', '1.7.0')) as dist_root:
      with env(PATH=os.path.join(dist_root, 'bin')):
        DistributionLocator.locate(minimum_version='1.6.0', maximum_version='1.7.999')

  def test_locate_via_jdk_home(self):
    with distribution(executables=exe('bin/java')) as dist_root:
      with env(JDK_HOME=dist_root):
        DistributionLocator.locate()

  def test_locate_via_java_home(self):
    with distribution(executables=exe('bin/java')) as dist_root:
      with env(JAVA_HOME=dist_root):
        DistributionLocator.locate()


class DistributionLinuxLocationTest(BaseDistributionLocationTest):
  def setUp(self):
    self.set_up_no_osx_discovery()

  @contextmanager
  def java_dist_dir(self):
    with distribution(executables=exe('bin/java', version='1')) as jdk1_home:
      with distribution(executables=exe('bin/java', version='2')) as jdk2_home:
        with temporary_dir() as java_dist_dir:
          jdk1_home_link = os.path.join(java_dist_dir, 'jdk1_home')
          jdk2_home_link = os.path.join(java_dist_dir, 'jdk2_home')
          os.symlink(jdk1_home, jdk1_home_link)
          os.symlink(jdk2_home, jdk2_home_link)

          original_java_dist_dir = DistributionLocator._JAVA_DIST_DIR
          DistributionLocator._JAVA_DIST_DIR = java_dist_dir
          try:
            yield jdk1_home_link, jdk2_home_link
          finally:
            DistributionLocator._JAVA_DIST_DIR = original_java_dist_dir

  def test_locate_jdk1(self):
    with env():
      with self.java_dist_dir() as (jdk1_home, _):
        dist = DistributionLocator.locate(maximum_version='1')
        self.assertEqual(jdk1_home, dist.home)

  def test_locate_jdk2(self):
    with env():
      with self.java_dist_dir() as (_, jdk2_home):
        dist = DistributionLocator.locate(minimum_version='2')
        self.assertEqual(jdk2_home, dist.home)

  def test_locate_trumps_path(self):
    with self.java_dist_dir() as (jdk1_home, jdk2_home):
      with distribution(executables=exe('bin/java', version='3')) as path_jdk:
        with env(PATH=os.path.join(path_jdk, 'bin')):
          dist = DistributionLocator.locate(minimum_version='2')
          self.assertEqual(jdk2_home, dist.home)
          dist = DistributionLocator.locate(minimum_version='3')
          self.assertEqual(path_jdk, dist.home)

  def test_locate_jdk_home_trumps(self):
    with self.java_dist_dir() as (jdk1_home, jdk2_home):
      with distribution(executables=exe('bin/java', version='3')) as jdk_home:
        with env(JDK_HOME=jdk_home):
          dist = DistributionLocator.locate()
          self.assertEqual(jdk_home, dist.home)
          dist = DistributionLocator.locate(maximum_version='1.1')
          self.assertEqual(jdk1_home, dist.home)
          dist = DistributionLocator.locate(minimum_version='1.1', maximum_version='2')
          self.assertEqual(jdk2_home, dist.home)

  def test_locate_java_home_trumps(self):
    with self.java_dist_dir() as (jdk1_home, jdk2_home):
      with distribution(executables=exe('bin/java', version='3')) as java_home:
        with env(JAVA_HOME=java_home):
          dist = DistributionLocator.locate()
          self.assertEqual(java_home, dist.home)
          dist = DistributionLocator.locate(maximum_version='1.1')
          self.assertEqual(jdk1_home, dist.home)
          dist = DistributionLocator.locate(minimum_version='1.1', maximum_version='2')
          self.assertEqual(jdk2_home, dist.home)


class DistributionOSXLocationTest(BaseDistributionLocationTest):
  def setUp(self):
    self.set_up_no_linux_discovery()

  @contextmanager
  def java_home_exe(self):
    with distribution(executables=exe('bin/java', version='1')) as jdk1_home:
      with distribution(executables=exe('bin/java', version='2')) as jdk2_home:
        with temporary_dir() as tmpdir:
          osx_java_home_exe = os.path.join(tmpdir, 'java_home')
          with safe_open(osx_java_home_exe, 'w') as fp:
            fp.write(textwrap.dedent("""
                #!/bin/sh
                echo '<?xml version="1.0" encoding="UTF-8"?>
                <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
                                       "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
                <plist version="1.0">
                <array>
                  <dict>
                    <key>JVMHomePath</key>
                    <string>{jdk1_home}</string>
                  </dict>
                  <dict>
                    <key>JVMHomePath</key>
                    <string>{jdk2_home}</string>
                  </dict>
                </array>
                </plist>
                '
              """.format(jdk1_home=jdk1_home, jdk2_home=jdk2_home)).strip())
          chmod_plus_x(osx_java_home_exe)

          original_osx_java_home_exe = DistributionLocator._OSX_JAVA_HOME_EXE
          DistributionLocator._OSX_JAVA_HOME_EXE = osx_java_home_exe
          try:
            yield jdk1_home, jdk2_home
          finally:
            DistributionLocator._OSX_JAVA_HOME_EXE = original_osx_java_home_exe

  def test_locate_jdk1(self):
    with env():
      with self.java_home_exe() as (jdk1_home, _):
        dist = DistributionLocator.locate()
        self.assertEqual(jdk1_home, dist.home)

  def test_locate_jdk2(self):
    with env():
      with self.java_home_exe() as (_, jdk2_home):
        dist = DistributionLocator.locate(minimum_version='2')
        self.assertEqual(jdk2_home, dist.home)

  def test_locate_trumps_path(self):
    with self.java_home_exe() as (jdk1_home, jdk2_home):
      with distribution(executables=exe('bin/java', version='3')) as path_jdk:
        with env(PATH=os.path.join(path_jdk, 'bin')):
          dist = DistributionLocator.locate()
          self.assertEqual(jdk1_home, dist.home)
          dist = DistributionLocator.locate(minimum_version='3')
          self.assertEqual(path_jdk, dist.home)

  def test_locate_jdk_home_trumps(self):
    with self.java_home_exe() as (jdk1_home, jdk2_home):
      with distribution(executables=exe('bin/java', version='3')) as jdk_home:
        with env(JDK_HOME=jdk_home):
          dist = DistributionLocator.locate()
          self.assertEqual(jdk_home, dist.home)
          dist = DistributionLocator.locate(maximum_version='1.1')
          self.assertEqual(jdk1_home, dist.home)
          dist = DistributionLocator.locate(minimum_version='1.1', maximum_version='2')
          self.assertEqual(jdk2_home, dist.home)

  def test_locate_java_home_trumps(self):
    with self.java_home_exe() as (jdk1_home, jdk2_home):
      with distribution(executables=exe('bin/java', version='3')) as java_home:
        with env(JAVA_HOME=java_home):
          dist = DistributionLocator.locate()
          self.assertEqual(java_home, dist.home)
          dist = DistributionLocator.locate(maximum_version='1.1')
          self.assertEqual(jdk1_home, dist.home)
          dist = DistributionLocator.locate(minimum_version='1.1', maximum_version='2')
          self.assertEqual(jdk2_home, dist.home)


class DistributionCachedTest(BaseDistributionLocationEnvOnlyTest):
  def setUp(self):
    super(DistributionCachedTest, self).setUp()

    # Save local cache and then flush so tests get a clean environment.
    local_cache = DistributionLocator._CACHE

    def restore_cache():
      DistributionLocator._CACHE = local_cache
    DistributionLocator._CACHE = {}
    self.addCleanup(restore_cache)

  def test_cached_good_min(self):
    with distribution(executables=exe('bin/java', '1.7.0_33')) as dist_root:
      with env(PATH=os.path.join(dist_root, 'bin')):
        DistributionLocator.cached(minimum_version='1.7.0_25')

  def test_cached_good_max(self):
    with distribution(executables=exe('bin/java', '1.7.0_33')) as dist_root:
      with env(PATH=os.path.join(dist_root, 'bin')):
        DistributionLocator.cached(maximum_version='1.7.0_50')

  def test_cached_good_bounds(self):
    with distribution(executables=exe('bin/java', '1.7.0_33')) as dist_root:
      with env(PATH=os.path.join(dist_root, 'bin')):
        DistributionLocator.cached(minimum_version='1.6.0_35', maximum_version='1.7.0_55')

  def test_cached_too_low(self):
    with distribution(executables=exe('bin/java', '1.7.0_33')) as dist_root:
      with env(PATH=os.path.join(dist_root, 'bin')):
        with self.assertRaises(Distribution.Error):
          DistributionLocator.cached(minimum_version='1.7.0_40')

  def test_cached_too_high(self):
    with distribution(executables=exe('bin/java', '1.7.0_83')) as dist_root:
      with env(PATH=os.path.join(dist_root, 'bin')):
        with self.assertRaises(Distribution.Error):
          DistributionLocator.cached(maximum_version='1.7.0_55')

  def test_cached_low_fault(self):
    with distribution(executables=exe('bin/java', '1.7.0_33')) as dist_root:
      with env(PATH=os.path.join(dist_root, 'bin')):
        with self.assertRaises(Distribution.Error):
          DistributionLocator.cached(minimum_version='1.7.0_35', maximum_version='1.7.0_55')

  def test_cached_high_fault(self):
    with distribution(executables=exe('bin/java', '1.7.0_33')) as dist_root:
      with env(PATH=os.path.join(dist_root, 'bin')):
        with self.assertRaises(Distribution.Error):
          DistributionLocator.cached(minimum_version='1.6.0_00', maximum_version='1.6.0_50')

  def test_cached_conflicting(self):
    with distribution(executables=exe('bin/java', '1.7.0_33')) as dist_root:
      with env(PATH=os.path.join(dist_root, 'bin')):
        with self.assertRaises(Distribution.Error):
          DistributionLocator.cached(minimum_version='1.7.0_00', maximum_version='1.6.0_50')

  def test_cached_bad_input(self):
    with distribution(executables=exe('bin/java', '1.7.0_33')) as dist_root:
      with env(PATH=os.path.join(dist_root, 'bin')):
        with self.assertRaises(ValueError):
          DistributionLocator.cached(minimum_version=1.7, maximum_version=1.8)


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
    with subsystem_instance(DistributionLocator):
      DistributionLocator.locate(jdk=False)

  @unittest.skipIf(not JAVAC, reason='No javac executable on the PATH.')
  def test_validate_live_jdk(self):
    Distribution(bin_path=os.path.dirname(self.JAVAC), jdk=True).validate()
    Distribution(bin_path=os.path.dirname(self.JAVAC), jdk=True).binary('javap')
    with subsystem_instance(DistributionLocator):
      DistributionLocator.locate(jdk=True)
