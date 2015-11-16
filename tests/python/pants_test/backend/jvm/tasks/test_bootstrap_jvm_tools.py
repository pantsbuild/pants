# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import subprocess
from contextlib import contextmanager

from pants.backend.jvm.subsystems.shader import Shading
from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.tasks.bootstrap_jvm_tools import BootstrapJvmTools
from pants.backend.jvm.tasks.jvm_tool_task_mixin import JvmToolTaskMixin
from pants.java.distribution.distribution import DistributionLocator
from pants.java.executor import SubprocessExecutor
from pants.task.task import Task
from pants.util.contextutil import open_zip
from pants_test.jvm.jvm_tool_task_test_base import JvmToolTaskTestBase
from pants_test.subsystem.subsystem_util import subsystem_instance


class BootstrapJvmToolsTestBase(JvmToolTaskTestBase):
  @contextmanager
  def execute_tool(self, classpath, main, args=None):
    with subsystem_instance(DistributionLocator):
      executor = SubprocessExecutor(DistributionLocator.cached())
      process = executor.spawn(classpath, main, args=args,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
      out, err = process.communicate()
      self.assertEqual(0, process.returncode)
      self.assertEqual('', err.strip())
      yield out


class BootstrapJvmToolsShadingTest(BootstrapJvmToolsTestBase):
  class JvmToolTask(JvmToolTaskMixin, Task):
    @classmethod
    def register_options(cls, register):
      super(BootstrapJvmToolsShadingTest.JvmToolTask, cls).register_options(register)

      # We know this version of ant has a dependency on org.apache.ant#ant-launcher;1.9.4
      ant_classpath = [JarDependency(org='org.apache.ant', name='ant', rev='1.9.4')]

      cls.register_jvm_tool(register,
                            'ant',
                            classpath=ant_classpath,
                            classpath_spec='test:ant')
      cls.register_jvm_tool(register,
                            'ant-shaded',
                            classpath=ant_classpath,
                            classpath_spec='test:ant',
                            main='org.apache.tools.ant.Main')

    def execute(self):
      return self.tool_classpath('ant'), self.tool_classpath('ant-shaded')

  @classmethod
  def task_type(cls):
    return cls.JvmToolTask

  def test_shaded_and_unshaded(self):
    task = self.prepare_execute(context=self.context())
    ant_classpath, ant_shaded_classpath = task.execute()

    # Verify the many jar -> 1 binary input jar for shading case is exercised.
    self.assertEqual(2, len(ant_classpath))
    self.assertEqual(1, len(ant_shaded_classpath))

    # Verify both the normal and shaded tools run successfully and produce the same output.
    def assert_run_ant_version(classpath):
      with self.execute_tool(classpath, 'org.apache.tools.ant.Main', args=['-version']) as out:
        self.assertTrue(out.strip().startswith('Apache Ant(TM) version 1.9.4'))

    assert_run_ant_version(ant_classpath)
    assert_run_ant_version(ant_shaded_classpath)

    # Verify that the same set of classes is encompassed by the normal and shaded tools.
    # Further check that just the tool main package is excluded from shading.
    def classfile_contents(classpath):
      contents = set()
      for jar in classpath:
        with open_zip(jar) as zip:
          contents.update(name for name in zip.namelist() if name.endswith('.class'))
      return contents

    classfiles = classfile_contents(ant_classpath)
    shaded_classfiles = classfile_contents(ant_shaded_classpath)
    self.assertEqual(len(classfiles), len(shaded_classfiles))

    excluded_classes = classfiles.intersection(shaded_classfiles)
    self.assertTrue(len(excluded_classes) >= 1)
    for excluded_class in excluded_classes:
      self.assertEqual('org/apache/tools/ant', os.path.dirname(excluded_class))

    prefix_len = len(Shading.SHADE_PREFIX)

    def strip_prefix(shaded):
      return set(classfile[prefix_len:] for classfile in shaded)

    self.assertEqual(classfiles - excluded_classes,
                     strip_prefix(shaded_classfiles - excluded_classes))


class BootstrapJvmToolsOptionalTest(BootstrapJvmToolsTestBase):
  class JvmToolTask(JvmToolTaskMixin, Task):
    @classmethod
    def register_options(cls, register):
      super(BootstrapJvmToolsOptionalTest.JvmToolTask, cls).register_options(register)
      cls.register_jvm_tool(register, 'plugins', classpath=[], classpath_spec='test:plugins')

    def execute(self):
      return self.tool_classpath('plugins')

  @classmethod
  def task_type(cls):
    return cls.JvmToolTask

  def test_unsupplied(self):
    task = self.prepare_execute(context=self.context())
    classpath = task.execute()
    self.assertEqual([], classpath)

  def test_supplied(self):
    self.make_target('test:plugins', JarLibrary, jars=[JarDependency('junit', 'junit', '4.12')])
    task = self.prepare_execute(context=self.context())
    classpath = task.execute()
    with self.execute_tool(classpath, 'org.junit.runner.JUnitCore') as out:
      self.assertIn('OK (0 tests)', out)


class BootstrapJvmToolsNonOptionalNoDefaultTest(BootstrapJvmToolsTestBase):
  class JvmToolTask(JvmToolTaskMixin, Task):
    @classmethod
    def register_options(cls, register):
      super(BootstrapJvmToolsNonOptionalNoDefaultTest.JvmToolTask, cls).register_options(register)
      cls.register_jvm_tool(register, 'checkstyle', classpath_spec='test:checkstyle')

    def execute(self):
      return self.tool_classpath('checkstyle')

  @classmethod
  def task_type(cls):
    return cls.JvmToolTask

  def test_unsupplied(self):
    with self.assertRaisesRegexp(BootstrapJvmTools.ToolResolveError,
                                 r'\s*Failed to resolve target for tool: test:checkstyle\..*'):
      self.execute(context=self.context())

  def test_supplied(self):
    self.make_target('test:checkstyle',
                     JarLibrary,
                     jars=[JarDependency('com.puppycrawl.tools', 'checkstyle', '6.10.1')])
    task = self.prepare_execute(context=self.context())
    classpath = task.execute()
    with self.execute_tool(classpath, 'com.puppycrawl.tools.checkstyle.Main', args=['-v']) as out:
      self.assertIn('6.10.1', out)
