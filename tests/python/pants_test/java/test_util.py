# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import errno
import os
import unittest
from contextlib import contextmanager

from mock import Mock, call, patch

from pants.java.executor import Executor
from pants.java.jar.manifest import Manifest
from pants.java.util import bundled_classpath, execute_java
from pants.util.contextutil import open_zip
from pants.util.dirutil import safe_mkdir, safe_mkdtemp, safe_rmtree, touch


class ExecuteJavaTest(unittest.TestCase):
  TOO_BIG = OSError(errno.E2BIG, os.strerror(errno.E2BIG))
  OTHER_OS_ERROR = OSError(errno.EIO, os.strerror(errno.EIO))
  OTHER_ERROR = RuntimeError()
  TEST_MAIN = 'foo.bar.main'
  TEST_CLASSPATH = ['A.jar', 'B.jar']
  BUNDLED_CLASSPATH = ['C.jar']

  def setUp(self):
    self.executor = Mock(spec=Executor)
    self.runner = Mock(spec=Executor.Runner)
    self.executor.runner = Mock(return_value=self.runner)
    self.runner.run = Mock(return_value=0)

  @contextmanager
  def mock_bundled_classpath_helper(self, argument_list_too_long=False):
    with patch('pants.java.util.bundled_classpath') as mock_bundled_classpath:
      yield mock_bundled_classpath

    if not argument_list_too_long:
      self.executor.runner.assert_called_once_with(self.TEST_CLASSPATH, self.TEST_MAIN,
                                                   args=None, jvm_options=None, cwd=None)
      self.runner.run.assert_called_once_with()
      mock_bundled_classpath.assert_not_called()
    else:
      self.executor.runner.assert_has_calls([
        call(self.TEST_CLASSPATH, self.TEST_MAIN, args=None, jvm_options=None, cwd=None),
        call(self.BUNDLED_CLASSPATH, self.TEST_MAIN, args=None, jvm_options=None, cwd=None)
      ])
      self.runner.run.assert_has_calls([call(), call()])
      mock_bundled_classpath.assert_called_once_with(self.TEST_CLASSPATH)

  def test_execute_java_no_error(self):
    with self.mock_bundled_classpath_helper():
      self.assertEquals(0, execute_java(self.TEST_CLASSPATH, self.TEST_MAIN,
                                        executor=self.executor))

  def test_execute_java_other_os_error(self):
    self.runner.run.side_effect = self.OTHER_OS_ERROR

    with self.mock_bundled_classpath_helper():
      with self.assertRaises(type(self.OTHER_OS_ERROR)):
        execute_java(self.TEST_CLASSPATH, self.TEST_MAIN, executor=self.executor)

  def test_execute_java_other_error(self):
    self.runner.run.side_effect = self.OTHER_ERROR

    with self.mock_bundled_classpath_helper():
      with self.assertRaises(type(self.OTHER_ERROR)):
        execute_java(self.TEST_CLASSPATH, self.TEST_MAIN, executor=self.executor)

  def test_execute_java_argument_list_too_long(self):
    with self.mock_bundled_classpath_helper(argument_list_too_long=True) as mock_bundled_classpath:
      mock_bundled_classpath.side_effect = fake_bundled_classpath
      self.runner.run.side_effect = [self.TOO_BIG, 0]
      self.assertEquals(0, execute_java(self.TEST_CLASSPATH, self.TEST_MAIN,
                                        executor=self.executor))

  def test_execute_java_argument_list_too_long_still_fail(self):
    with self.mock_bundled_classpath_helper(argument_list_too_long=True) as mock_bundled_classpath:
      mock_bundled_classpath.side_effect = fake_bundled_classpath

      # still may fail with OTHER_ERROR error
      self.runner.run.side_effect = [self.TOO_BIG, self.OTHER_ERROR]
      with self.assertRaises(type(self.OTHER_ERROR)):
        execute_java(self.TEST_CLASSPATH, self.TEST_MAIN, executor=self.executor)

  def test_execute_java_argument_list_too_long_still_fail_still_too_long(self):
    with self.mock_bundled_classpath_helper(argument_list_too_long=True) as mock_bundled_classpath:
      mock_bundled_classpath.side_effect = fake_bundled_classpath

      # very unlikely but still may fail with TOO_BIG error
      self.runner.run.side_effect = [self.TOO_BIG, self.TOO_BIG]
      with self.assertRaises(type(self.TOO_BIG)):
        execute_java(self.TEST_CLASSPATH, self.TEST_MAIN, executor=self.executor)


@contextmanager
def fake_bundled_classpath(classpath):
  yield ExecuteJavaTest.BUNDLED_CLASSPATH


class BundledClasspathTest(unittest.TestCase):
  def test_bundled_classpath(self):
    """This creates the following classpath
      basedir/libs/A.jar:basedir/resources
    """
    RESOURCES = 'resources'
    LIB_DIR = 'libs'
    JAR_FILE = 'A.jar'

    basedir = safe_mkdtemp()
    lib_dir = os.path.join(basedir, LIB_DIR)
    resource_dir = os.path.join(lib_dir, RESOURCES)
    jar_file = os.path.join(lib_dir, JAR_FILE)

    for dir in (lib_dir, resource_dir):
      safe_mkdir(dir)
    touch(jar_file)

    classpath = [jar_file, resource_dir]

    with bundled_classpath(classpath) as bundled_cp:
      self.assertEquals(1, len(bundled_cp))
      bundled_jar = bundled_cp[0]
      self.assertTrue(os.path.exists(bundled_jar))

      with open_zip(bundled_jar) as synthetic_jar:
        self.assertListEqual([Manifest.PATH], synthetic_jar.namelist())
        # manifest should contain the absolute path of both jar and resource directory
        self.assertEquals('{}: {} {}/\n'.format(Manifest.CLASS_PATH, os.path.realpath(jar_file),
                                                os.path.realpath(resource_dir)),
                          synthetic_jar.read(Manifest.PATH).replace('\n ', ''))

    safe_rmtree(resource_dir)
