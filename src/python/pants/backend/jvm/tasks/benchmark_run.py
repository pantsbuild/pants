# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
import shutil

from pants.backend.jvm.tasks.jvm_tool_task_mixin import JvmToolTaskMixin
from pants.backend.jvm.tasks.jvm_task import JvmTask
from pants.base.exceptions import TaskError
from pants.java.util import execute_java


class BenchmarkRun(JvmTask, JvmToolTaskMixin):
  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    option_group.add_option(mkflag("target"), dest="target_class", action="append",
                            help="Name of the benchmark class.")

    option_group.add_option(mkflag("memory"), mkflag("memory", negate=True),
                            dest="memory_profiling", default=False,
                            action="callback", callback=mkflag.set_bool,
                            help="[%default] Enable memory profiling.")

    option_group.add_option(mkflag("debug"), mkflag("debug", negate=True),
                            dest="debug", default=False,
                            action="callback", callback=mkflag.set_bool,
                            help="[%default] Enable caliper debug mode.")

    option_group.add_option(mkflag("caliper-args"), dest="extra_caliper_args", default=[],
                            action="append",
                            help="Allows the user to pass additional command line options to "
                                 "caliper. Can be used multiple times and arguments will be "
                                 "concatenated. Example use: --bench-caliper-args='-Dsize=10,20 "
                                 "-Dcomplex=true,false' --bench-caliper-args=-Dmem=1,2,3")

  def __init__(self, *args, **kwargs):
    super(BenchmarkRun, self).__init__(*args, **kwargs)

    config = self.context.config
    self.confs = config.getlist('benchmark-run', 'confs', default=['default'])
    self.jvm_args = config.getlist('benchmark-run', 'jvm_args',
                                   default=['-Xmx1g', '-XX:MaxPermSize=256m'])

    self._benchmark_bootstrap_key = 'benchmark-tool'
    benchmark_bootstrap_tools = config.getlist('benchmark-run', 'bootstrap-tools',
                                               default=[':benchmark-caliper-0.5'])
    self.register_jvm_tool(self._benchmark_bootstrap_key,
                                                  benchmark_bootstrap_tools)
    self._agent_bootstrap_key = 'benchmark-agent'
    agent_bootstrap_tools = config.getlist('benchmark-run', 'agent_profile',
                                           default=[':benchmark-java-allocation-instrumenter-2.1'])
    self.register_jvm_tool(self._agent_bootstrap_key, agent_bootstrap_tools)

    # TODO(Steve Gury):
    # Find all the target classes from the Benchmark target itself
    # https://jira.twitter.biz/browse/AWESOME-1938
    self.caliper_args = self.context.options.target_class

    if self.context.options.memory_profiling:
      self.caliper_args += ['--measureMemory']

    if self.context.options.debug:
      self.jvm_args.extend(self.context.config.getlist('jvm', 'debug_args'))
      self.caliper_args += ['--debug']

    self.caliper_args.extend(self.context.options.extra_caliper_args)

  def prepare(self, round_manager):
    # TODO(John Sirois): these are fake requirements in order to force compile run before this
    # phase. Introduce a RuntimeClasspath product for JvmCompile and PrepareResources to populate
    # and depend on that.
    # See: https://github.com/pantsbuild/pants/issues/310
    round_manager.require_data('resources_by_target')
    round_manager.require_data('classes_by_target')

  def execute(self):
    # For rewriting JDK classes to work, the JAR file has to be listed specifically in
    # the JAR manifest as something that goes in the bootclasspath.
    # The MANIFEST list a jar 'allocation.jar' this is why we have to rename it
    agent_tools_classpath = self.tool_classpath(self._agent_bootstrap_key)
    agent_jar = agent_tools_classpath[0]
    allocation_jar = os.path.join(os.path.dirname(agent_jar), "allocation.jar")

    # TODO(Steve Gury): Find a solution to avoid copying the jar every run and being resilient
    # to version upgrade
    shutil.copyfile(agent_jar, allocation_jar)
    os.environ['ALLOCATION_JAR'] = str(allocation_jar)

    benchmark_tools_classpath = self.tool_classpath(self._benchmark_bootstrap_key)

    targets = self.context.targets()
    classpath = self.classpath(benchmark_tools_classpath,
                               confs=self.confs,
                               exclusives_classpath=self.get_base_classpath_for_target(targets[0]))

    caliper_main = 'com.google.caliper.Runner'
    exit_code = execute_java(classpath=classpath,
                             main=caliper_main,
                             jvm_options=self.jvm_args,
                             args=self.caliper_args,
                             workunit_factory=self.context.new_workunit,
                             workunit_name='caliper')
    if exit_code != 0:
      raise TaskError('java %s ... exited non-zero (%i)' % (caliper_main, exit_code))
