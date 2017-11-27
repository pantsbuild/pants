# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import unittest
from contextlib import contextmanager

from mock import Mock, patch

from pants.java.executor import Executor
from pants.java.jar.manifest import Manifest
from pants.java.util import execute_java, safe_classpath
from pants.util.contextutil import open_zip
from pants.util.dirutil import safe_mkdir, safe_mkdtemp, touch


class ExecuteJavaTest(unittest.TestCase):
  """
    :API: public
  """
  EXECUTOR_ERROR = Executor.Error()
  TEST_MAIN = 'foo.bar.main'
  TEST_CLASSPATH = ['A.jar', 'B.jar']
  SAFE_CLASSPATH = ['C.jar']
  SYNTHETIC_JAR_DIR = 'somewhere'

  def setUp(self):
    """
    :API: public
    """
    self.executor = Mock(spec=Executor)
    self.runner = Mock(spec=Executor.Runner)
    self.executor.runner = Mock(return_value=self.runner)
    self.runner.run = Mock(return_value=0)

  @contextmanager
  def mock_safe_classpath_helper(self, create_synthetic_jar=True):
    """
    :API: public
    """
    with patch('pants.java.util.safe_classpath') as mock_safe_classpath:
      mock_safe_classpath.side_effect = fake_safe_classpath
      yield mock_safe_classpath

    self.runner.run.assert_called_once_with()
    if create_synthetic_jar:
      self.executor.runner.assert_called_once_with(self.SAFE_CLASSPATH, self.TEST_MAIN,
                                                    args=None, jvm_options=None, cwd=None)
      mock_safe_classpath.assert_called_once_with(self.TEST_CLASSPATH, self.SYNTHETIC_JAR_DIR)
    else:
      self.executor.runner.assert_called_once_with(self.TEST_CLASSPATH, self.TEST_MAIN,
                                                    args=None, jvm_options=None, cwd=None)
      mock_safe_classpath.assert_not_called()

  def test_execute_java_no_error(self):
    """
    :API: public
    """
    with self.mock_safe_classpath_helper():
      self.assertEquals(0, execute_java(self.TEST_CLASSPATH, self.TEST_MAIN,
                                        executor=self.executor,
                                        synthetic_jar_dir=self.SYNTHETIC_JAR_DIR))

  def test_execute_java_executor_error(self):
    """
    :API: public
    """
    with self.mock_safe_classpath_helper():
      self.runner.run.side_effect = self.EXECUTOR_ERROR

      with self.assertRaises(type(self.EXECUTOR_ERROR)):
        execute_java(self.TEST_CLASSPATH, self.TEST_MAIN, executor=self.executor,
                     synthetic_jar_dir=self.SYNTHETIC_JAR_DIR)

  def test_execute_java_no_synthentic_jar(self):
    """
    :API: public
    """
    with self.mock_safe_classpath_helper(create_synthetic_jar=False):
      self.assertEquals(0, execute_java(self.TEST_CLASSPATH, self.TEST_MAIN,
                                        executor=self.executor,
                                        create_synthetic_jar=False))


def fake_safe_classpath(classpath, synthetic_jar_dir):
  return ExecuteJavaTest.SAFE_CLASSPATH


class SafeClasspathTest(unittest.TestCase):
  def test_safe_classpath(self):
    """For directory structure like:

       ./
       ./libs/A.jar
       ./libs/resources/
       ./synthetic_jar_dir

       Verify a synthetic jar with the following classpath in manifest is created:

        Class-Path: ../libs/A.jar:../libs/resources/
    """
    RESOURCES = 'resources'
    LIB_DIR = 'libs'
    JAR_FILE = 'A.jar'
    SYNTHENTIC_JAR_DIR = 'synthetic_jar_dir'

    basedir = safe_mkdtemp()
    lib_dir = os.path.join(basedir, LIB_DIR)
    synthetic_jar_dir = os.path.join(basedir, SYNTHENTIC_JAR_DIR)
    resource_dir = os.path.join(lib_dir, RESOURCES)
    jar_file = os.path.join(lib_dir, JAR_FILE)

    for dir in (lib_dir, resource_dir, synthetic_jar_dir):
      safe_mkdir(dir)
    touch(jar_file)

    classpath = [jar_file, resource_dir]

    safe_cp = safe_classpath(classpath, synthetic_jar_dir)
    self.assertEquals(1, len(safe_cp))
    safe_jar = safe_cp[0]
    self.assertTrue(os.path.exists(safe_jar))
    self.assertEquals(synthetic_jar_dir, os.path.dirname(safe_jar))

    with open_zip(safe_jar) as synthetic_jar:
      self.assertListEqual([Manifest.PATH], synthetic_jar.namelist())
      # manifest should contain the relative path of both jar and resource directory
      self.assertEquals('{}: ../{}/{} ../{}/{}/\n'.format(Manifest.CLASS_PATH, LIB_DIR, JAR_FILE,
                                                          LIB_DIR, RESOURCES),
                        synthetic_jar.read(Manifest.PATH).replace('\n ', ''))
