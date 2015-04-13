# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import subprocess

from pants.backend.core.tasks.task import Task
from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.tasks.jvm_tool_task_mixin import JvmToolTaskMixin
from pants.java.executor import SubprocessExecutor
from pants.java.jar.shader import Shader
from pants.util.contextutil import open_zip
from pants_test.jvm.jvm_tool_task_test_base import JvmToolTaskTestBase


class JvmToolTask(JvmToolTaskMixin, Task):
  @classmethod
  def register_options(cls, register):
    super(JvmToolTask, cls).register_options(register)
    cls.register_jvm_tool(register, 'ant', default=['test:ant'])
    cls.register_jvm_tool(register, 'ant-shaded', default=['test:ant'],
                          main='org.apache.tools.ant.Main')

  def execute(self):
    return self.tool_classpath('ant'), self.tool_classpath('ant-shaded')


class BootstrapJvmToolsTest(JvmToolTaskTestBase):
  @classmethod
  def task_type(cls):
    return JvmToolTask

  def setUp(self):
    super(BootstrapJvmToolsTest, self).setUp()
    self.set_options_for_scope('', pants_bootstrapdir='~/.cache/pants', max_subprocess_args=100)

  def test_shaded_and_unshaded(self):
    # We know this version of ant has a dependency on org.apache.ant#ant-launcher;1.9.4
    self.make_target(spec='test:ant',
                     target_type=JarLibrary,
                     jars=[JarDependency(org='org.apache.ant', name='ant', rev='1.9.4')])

    task = self.execute(context=self.context())
    ant_classpath, ant_shaded_classpath = task.execute()

    # Verify the many jar -> 1 binary input jar for shading case is exercised.
    self.assertEqual(2, len(ant_classpath))
    self.assertEqual(1, len(ant_shaded_classpath))

    # Verify both the normal and shaded tools run successfully and produce the same output.
    executor = SubprocessExecutor()

    def assert_run_ant_version(classpath):
      process = executor.spawn(classpath, 'org.apache.tools.ant.Main', args=['-version'],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
      out, err = process.communicate()
      self.assertEqual(0, process.returncode)
      self.assertTrue(out.strip().startswith('Apache Ant(TM) version 1.9.4'))
      self.assertEqual('', err.strip())

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

    prefix_len = len(Shader.SHADE_PREFIX)

    def strip_prefix(shaded):
      return set(classfile[prefix_len:] for classfile in shaded)

    self.assertEqual(classfiles - excluded_classes,
                     strip_prefix(shaded_classfiles - excluded_classes))
