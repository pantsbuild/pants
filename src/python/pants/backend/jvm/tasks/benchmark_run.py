# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import shutil

from pants.backend.jvm.tasks.jvm_task import JvmTask
from pants.backend.jvm.tasks.jvm_tool_task_mixin import JvmToolTaskMixin
from pants.base.exceptions import TaskError
from pants.java.util import execute_java


class BenchmarkRun(JvmTask, JvmToolTaskMixin):
  @classmethod
  def register_options(cls, register):
    super(BenchmarkRun, cls).register_options(register)
    register('--target', help='Name of the benchmark class. This is a mandatory argument.')
    register('--memory', default=False, action='store_true', help='Enable memory profiling.')
    cls.register_jvm_tool(register, 'benchmark-tool', default=['//:benchmark-caliper-0.5'])
    cls.register_jvm_tool(register, 'benchmark-agent',
                          default=['//:benchmark-java-allocation-instrumenter-2.1'])

  @classmethod
  def prepare(cls, options, round_manager):
    super(BenchmarkRun, cls).prepare(options, round_manager)

    # TODO(John Sirois): these are fake requirements in order to force compile to run before this
    # goal. Introduce a RuntimeClasspath product for JvmCompile and PrepareResources to populate
    # and depend on that.
    # See: https://github.com/pantsbuild/pants/issues/310
    round_manager.require_data('resources_by_target')
    round_manager.require_data('classes_by_target')

  def __init__(self, *args, **kwargs):
    super(BenchmarkRun, self).__init__(*args, **kwargs)
    # TODO(Steve Gury):
    # Find all the target classes from the Benchmark target itself
    # https://jira.twitter.biz/browse/AWESOME-1938
    if not self.get_options().target:
      raise ValueError('Mandatory argument --target must be specified.')
    self.args.insert(0, self.get_options().target)
    if self.get_options().memory:
      self.args.append('--measureMemory')
    if self.get_options().debug:
      self.args.append('--debug')

  def execute(self):
    # For rewriting JDK classes to work, the JAR file has to be listed specifically in
    # the JAR manifest as something that goes in the bootclasspath.
    # The MANIFEST list a jar 'allocation.jar' this is why we have to rename it
    agent_tools_classpath = self.tool_classpath('benchmark-agent')
    agent_jar = agent_tools_classpath[0]
    allocation_jar = os.path.join(os.path.dirname(agent_jar), "allocation.jar")

    # TODO(Steve Gury): Find a solution to avoid copying the jar every run and being resilient
    # to version upgrade
    shutil.copyfile(agent_jar, allocation_jar)
    os.environ['ALLOCATION_JAR'] = str(allocation_jar)

    benchmark_tools_classpath = self.tool_classpath('benchmark-tool')

    classpath = self.classpath(self.context.targets(), benchmark_tools_classpath)

    caliper_main = 'com.google.caliper.Runner'
    exit_code = execute_java(classpath=classpath,
                             main=caliper_main,
                             jvm_options=self.jvm_options,
                             args=self.args,
                             workunit_factory=self.context.new_workunit,
                             workunit_name='caliper')
    if exit_code != 0:
      raise TaskError('java %s ... exited non-zero (%i)' % (caliper_main, exit_code))
