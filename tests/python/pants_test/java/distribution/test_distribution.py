# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import subprocess
import textwrap
import unittest
from contextlib import contextmanager

from twitter.common.collections import maybe_list

from pants.base.revision import Revision
from pants.java.distribution.distribution import (Distribution, DistributionLocator,
                                                  _EnvVarEnvironment, _LinuxEnvironment, _Locator,
                                                  _OSXEnvironment, _UnknownEnvironment)
from pants.util.contextutil import environment_as, temporary_dir, temporary_file
from pants.util.dirutil import chmod_plus_x, safe_open, touch
from pants_test.subsystem.subsystem_util import global_subsystem_instance


class EXE(object):
  def __init__(self, relpath, version=None):
    self._relpath = relpath
    self._version = version

  @property
  def relpath(self):
    return self._relpath

  def contents(self, java_home):
    return textwrap.dedent("""
        #!/bin/sh
        if [ $# -ne 3 ]; then
          # Sanity check a classpath switch with a value plus the classname for main
          echo "Expected 3 arguments, got $#: $@" >&2
          exit 1
        fi
        echo "java.home={}"
        {}
      """.format(java_home,
                 'echo "java.version={}"'.format(self._version) if self._version else '')).strip()


@contextmanager
def distribution(files=None, executables=None, java_home=None):
  with temporary_dir() as dist_root:
    for f in maybe_list(files or ()):
      touch(os.path.join(dist_root, f))
    for executable in maybe_list(executables or (), expected_type=EXE):
      path = os.path.join(dist_root, executable.relpath)
      with safe_open(path, 'w') as fp:
        java_home = os.path.join(dist_root, java_home) if java_home else dist_root
        fp.write(executable.contents(java_home))
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

    with distribution(executables=EXE('bin/java')) as dist_root:
      Distribution(bin_path=os.path.join(dist_root, 'bin')).validate()

  def test_validate_jre(self):
    with distribution(executables=EXE('bin/java')) as dist_root:
      Distribution(bin_path=os.path.join(dist_root, 'bin'), jdk=False).validate()

  def test_validate_jdk(self):
    with distribution(executables=EXE('bin/java')) as dist_root:
      with self.assertRaises(Distribution.Error):
        Distribution(bin_path=os.path.join(dist_root, 'bin'), jdk=True).validate()

    with distribution(executables=[EXE('bin/java'), EXE('bin/javac')]) as dist_root:
      Distribution(bin_path=os.path.join(dist_root, 'bin'), jdk=True).validate()

    with distribution(executables=[EXE('jre/bin/java'), EXE('bin/javac')],
                      java_home='jre') as dist_root:
      Distribution(bin_path=os.path.join(dist_root, 'jre/bin'), jdk=True).validate()

  def test_validate_version(self):
    with distribution(executables=EXE('bin/java', '1.7.0_25')) as dist_root:
      with self.assertRaises(Distribution.Error):
        Distribution(bin_path=os.path.join(dist_root, 'bin'), minimum_version='1.7.0_45').validate()
    with distribution(executables=EXE('bin/java', '1.8.0_1')) as dist_root:
      with self.assertRaises(Distribution.Error):
        Distribution(bin_path=os.path.join(dist_root, 'bin'), maximum_version='1.8').validate()

    with distribution(executables=EXE('bin/java', '1.7.0_25')) as dist_root:
      Distribution(bin_path=os.path.join(dist_root, 'bin'), minimum_version='1.7.0_25').validate()
      Distribution(bin_path=os.path.join(dist_root, 'bin'),
                   minimum_version=Revision.lenient('1.6')).validate()
      Distribution(bin_path=os.path.join(dist_root, 'bin'),
                   minimum_version='1.7.0_25',
                   maximum_version='1.7.999').validate()

  def test_validated_binary(self):
    with distribution(files='bin/jar', executables=EXE('bin/java')) as dist_root:
      with self.assertRaises(Distribution.Error):
        Distribution(bin_path=os.path.join(dist_root, 'bin')).binary('jar')

    with distribution(executables=[EXE('bin/java'), EXE('bin/jar')]) as dist_root:
      Distribution(bin_path=os.path.join(dist_root, 'bin')).binary('jar')

    with distribution(executables=[EXE('jre/bin/java'), EXE('bin/jar')],
                      java_home='jre') as dist_root:
      with self.assertRaises(Distribution.Error):
        Distribution(bin_path=os.path.join(dist_root, 'jre', 'bin')).binary('jar')

    with distribution(executables=[EXE('jre/bin/java'), EXE('bin/jar'), EXE('bin/javac')],
                      java_home='jre') as dist_root:
      Distribution(bin_path=os.path.join(dist_root, 'jre', 'bin')).binary('jar')

    with distribution(executables=[EXE('jre/bin/java'), EXE('jre/bin/java_vm'), EXE('bin/javac')],
                      java_home='jre') as dist_root:
      Distribution(bin_path=os.path.join(dist_root, 'jre', 'bin')).binary('java_vm')

  def test_validated_library(self):
    with distribution(executables=EXE('bin/java')) as dist_root:
      with self.assertRaises(Distribution.Error):
        Distribution(bin_path=os.path.join(dist_root, 'bin')).find_libs(['tools.jar'])

    with distribution(executables=EXE('bin/java'), files='lib/tools.jar') as dist_root:
      dist = Distribution(bin_path=os.path.join(dist_root, 'bin'))
      self.assertEqual([os.path.join(dist_root, 'lib', 'tools.jar')],
                       dist.find_libs(['tools.jar']))

    with distribution(executables=[EXE('jre/bin/java'), EXE('bin/javac')],
                      files=['lib/tools.jar', 'jre/lib/rt.jar'],
                      java_home='jre') as dist_root:
      dist = Distribution(bin_path=os.path.join(dist_root, 'jre/bin'))
      self.assertEqual([os.path.join(dist_root, 'lib', 'tools.jar'),
                        os.path.join(dist_root, 'jre', 'lib', 'rt.jar')],
                       dist.find_libs(['tools.jar', 'rt.jar']))


class DistributionEnvLocationTest(unittest.TestCase):
  def setUp(self):
    super(DistributionEnvLocationTest, self).setUp()
    self.locator = _Locator(_EnvVarEnvironment())

  def test_locate_none(self):
    with env():
      with self.assertRaises(Distribution.Error):
        self.locator.locate()

  def test_locate_java_not_executable(self):
    with distribution(files='bin/java') as dist_root:
      with env(PATH=os.path.join(dist_root, 'bin')):
        with self.assertRaises(Distribution.Error):
          self.locator.locate()

  def test_locate_jdk_is_jre(self):
    with distribution(executables=EXE('bin/java')) as dist_root:
      with env(PATH=os.path.join(dist_root, 'bin')):
        with self.assertRaises(Distribution.Error):
          self.locator.locate(jdk=True)

  def test_locate_version_to_low(self):
    with distribution(executables=EXE('bin/java', '1.6.0')) as dist_root:
      with env(PATH=os.path.join(dist_root, 'bin')):
        with self.assertRaises(Distribution.Error):
          self.locator.locate(minimum_version='1.7.0')

  def test_locate_version_to_high(self):
    with distribution(executables=EXE('bin/java', '1.8.0')) as dist_root:
      with env(PATH=os.path.join(dist_root, 'bin')):
        with self.assertRaises(Distribution.Error):
          self.locator.locate(maximum_version='1.7.999')

  def test_locate_invalid_jdk_home(self):
    with distribution(executables=EXE('java')) as dist_root:
      with env(JDK_HOME=dist_root):
        with self.assertRaises(Distribution.Error):
          self.locator.locate()

  def test_locate_invalid_java_home(self):
    with distribution(executables=EXE('java')) as dist_root:
      with env(JAVA_HOME=dist_root):
        with self.assertRaises(Distribution.Error):
          self.locator.locate()

  def test_locate_jre_by_path(self):
    with distribution(executables=EXE('bin/java')) as dist_root:
      with env(PATH=os.path.join(dist_root, 'bin')):
        self.locator.locate()

  def test_locate_jdk_by_path(self):
    with distribution(executables=[EXE('bin/java'), EXE('bin/javac')]) as dist_root:
      with env(PATH=os.path.join(dist_root, 'bin')):
        self.locator.locate(jdk=True)

  def test_locate_jdk_via_jre_path(self):
    with distribution(executables=[EXE('jre/bin/java'), EXE('bin/javac')],
                      java_home='jre') as dist_root:
      with env(PATH=os.path.join(dist_root, 'jre', 'bin')):
        self.locator.locate(jdk=True)

  def test_locate_version_greater_then_or_equal(self):
    with distribution(executables=EXE('bin/java', '1.7.0')) as dist_root:
      with env(PATH=os.path.join(dist_root, 'bin')):
        self.locator.locate(minimum_version='1.6.0')

  def test_locate_version_less_then_or_equal(self):
    with distribution(executables=EXE('bin/java', '1.7.0')) as dist_root:
      with env(PATH=os.path.join(dist_root, 'bin')):
        self.locator.locate(maximum_version='1.7.999')

  def test_locate_version_within_range(self):
    with distribution(executables=EXE('bin/java', '1.7.0')) as dist_root:
      with env(PATH=os.path.join(dist_root, 'bin')):
        self.locator.locate(minimum_version='1.6.0', maximum_version='1.7.999')

  def test_locate_via_jdk_home(self):
    with distribution(executables=EXE('bin/java')) as dist_root:
      with env(JDK_HOME=dist_root):
        self.locator.locate()

  def test_locate_via_java_home(self):
    with distribution(executables=EXE('bin/java')) as dist_root:
      with env(JAVA_HOME=dist_root):
        self.locator.locate()


class DistributionLinuxLocationTest(unittest.TestCase):
  @contextmanager
  def locator(self):
    with distribution(executables=EXE('bin/java', version='1')) as jdk1_home:
      with distribution(executables=EXE('bin/java', version='2')) as jdk2_home:
        with temporary_dir() as java_dist_dir1, temporary_dir() as java_dist_dir2:
          locator = _Locator(_UnknownEnvironment(_EnvVarEnvironment(),
                                                 _LinuxEnvironment(java_dist_dir1, java_dist_dir2)))
          jdk1_home_link = os.path.join(java_dist_dir1, 'jdk1_home')
          jdk2_home_link = os.path.join(java_dist_dir2, 'jdk2_home')
          os.symlink(jdk1_home, jdk1_home_link)
          os.symlink(jdk2_home, jdk2_home_link)
          yield locator, jdk1_home_link, jdk2_home_link

  def test_locate_jdk1(self):
    with env():
      with self.locator() as (locator, jdk1_home, _):
        dist = locator.locate(maximum_version='1')
        self.assertEqual(jdk1_home, dist.home)

  def test_locate_jdk2(self):
    with env():
      with self.locator() as (locator, _, jdk2_home):
        dist = locator.locate(minimum_version='2')
        self.assertEqual(jdk2_home, dist.home)

  def test_default_to_path(self):
    with self.locator() as (locator, jdk1_home, jdk2_home):
      with distribution(executables=EXE('bin/java', version='3')) as path_jdk:
        with env(PATH=os.path.join(path_jdk, 'bin')):
          dist = locator.locate(minimum_version='2')
          self.assertEqual(path_jdk, dist.home)
          dist = locator.locate(maximum_version='2')
          self.assertEqual(jdk1_home, dist.home)

  def test_locate_jdk_home_trumps(self):
    with self.locator() as (locator, jdk1_home, jdk2_home):
      with distribution(executables=EXE('bin/java', version='3')) as jdk_home:
        with env(JDK_HOME=jdk_home):
          dist = locator.locate()
          self.assertEqual(jdk_home, dist.home)
          dist = locator.locate(maximum_version='1.1')
          self.assertEqual(jdk1_home, dist.home)
          dist = locator.locate(minimum_version='1.1', maximum_version='2')
          self.assertEqual(jdk2_home, dist.home)

  def test_locate_java_home_trumps(self):
    with self.locator() as (locator, jdk1_home, jdk2_home):
      with distribution(executables=EXE('bin/java', version='3')) as java_home:
        with env(JAVA_HOME=java_home):
          dist = locator.locate()
          self.assertEqual(java_home, dist.home)
          dist = locator.locate(maximum_version='1.1')
          self.assertEqual(jdk1_home, dist.home)
          dist = locator.locate(minimum_version='1.1', maximum_version='2')
          self.assertEqual(jdk2_home, dist.home)


class DistributionOSXLocationTest(unittest.TestCase):
  @contextmanager
  def java_home_exe(self):
    with distribution(executables=EXE('bin/java', version='1')) as jdk1_home:
      with distribution(executables=EXE('bin/java', version='2')) as jdk2_home:
        with temporary_file() as osx_java_home_exe:
          osx_java_home_exe.write(textwrap.dedent("""
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
          osx_java_home_exe.close()
          chmod_plus_x(osx_java_home_exe.name)
          locator = _Locator(_UnknownEnvironment(_EnvVarEnvironment(),
                                                 _OSXEnvironment(osx_java_home_exe.name)))
          yield locator, jdk1_home, jdk2_home

  def test_locate_jdk1(self):
    with env():
      with self.java_home_exe() as (locator, jdk1_home, _):
        dist = locator.locate()
        self.assertEqual(jdk1_home, dist.home)

  def test_locate_jdk2(self):
    with env():
      with self.java_home_exe() as (locator, _, jdk2_home):
        dist = locator.locate(minimum_version='2')
        self.assertEqual(jdk2_home, dist.home)

  def test_default_to_path(self):
    with self.java_home_exe() as (locator, jdk1_home, jdk2_home):
      with distribution(executables=EXE('bin/java', version='3')) as path_jdk:
        with env(PATH=os.path.join(path_jdk, 'bin')):
          dist = locator.locate(minimum_version='2')
          self.assertEqual(path_jdk, dist.home)
          dist = locator.locate(maximum_version='2')
          self.assertEqual(jdk1_home, dist.home)

  def test_locate_jdk_home_trumps(self):
    with self.java_home_exe() as (locator, jdk1_home, jdk2_home):
      with distribution(executables=EXE('bin/java', version='3')) as jdk_home:
        with env(JDK_HOME=jdk_home):
          dist = locator.locate()
          self.assertEqual(jdk_home, dist.home)
          dist = locator.locate(maximum_version='1.1')
          self.assertEqual(jdk1_home, dist.home)
          dist = locator.locate(minimum_version='1.1', maximum_version='2')
          self.assertEqual(jdk2_home, dist.home)

  def test_locate_java_home_trumps(self):
    with self.java_home_exe() as (locator, jdk1_home, jdk2_home):
      with distribution(executables=EXE('bin/java', version='3')) as java_home:
        with env(JAVA_HOME=java_home):
          dist = locator.locate()
          self.assertEqual(java_home, dist.home)
          dist = locator.locate(maximum_version='1.1')
          self.assertEqual(jdk1_home, dist.home)
          dist = locator.locate(minimum_version='1.1', maximum_version='2')
          self.assertEqual(jdk2_home, dist.home)


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
    locator = global_subsystem_instance(DistributionLocator)
    locator.cached(jdk=False)

  @unittest.skipIf(not JAVAC, reason='No javac executable on the PATH.')
  def test_validate_live_jdk(self):
    Distribution(bin_path=os.path.dirname(self.JAVAC), jdk=True).validate()
    Distribution(bin_path=os.path.dirname(self.JAVAC), jdk=True).binary('javap')
    locator = global_subsystem_instance(DistributionLocator)
    locator.cached(jdk=True)
