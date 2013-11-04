# ==================================================================================================
# Copyright 2013 Twitter, Inc.
# --------------------------------------------------------------------------------------------------
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this work except in compliance with the License.
# You may obtain a copy of the License in the LICENSE file, or at:
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==================================================================================================

import os
import shutil
from twitter.pants.binary_util import runjava_indivisible
from twitter.pants.tasks import Task, TaskError
from twitter.pants.tasks.jvm_task import JvmTask

class BenchmarkRun(JvmTask):
  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    option_group.add_option(mkflag("target"), dest = "target_class", action="append",
                            help = "Name of the benchmark class.")

    option_group.add_option(mkflag("memory"), mkflag("memory", negate=True),
                            dest="memory_profiling", default=False,
                            action="callback", callback=mkflag.set_bool,
                            help="[%default] Enable memory profiling.")

    option_group.add_option(mkflag("debug"), mkflag("debug", negate=True),
                            dest="debug", default=False,
                            action="callback", callback=mkflag.set_bool,
                            help="[%default] Enable caliper debug mode.")

  def __init__(self, context):
    Task.__init__(self, context)
    config = context.config
    self.confs = config.getlist('benchmark-run', 'confs')
    self.java_args = config.getlist('benchmark-run', 'args',
                                    default=['-Xmx1g', '-XX:MaxPermSize=256m'])

    self._benchmark_bootstrap_tools = config.getlist('benchmark-run', 'bootstrap-tools',
                                                     default=[':benchmark-caliper-0.5'])
    self._agent_bootstrap_tools = config.getlist('benchmark-run',
                                                 'agent_profile',
                                                 default=[':benchmark-java-allocation-instrumenter-2.1'])

    self._bootstrap_utils.register_all([self._benchmark_bootstrap_tools,
                                        self._agent_bootstrap_tools])

    # TODO(Steve Gury):
    # Find all the target classes from the Benchmark target itself
    # https://jira.twitter.biz/browse/AWESOME-1938
    self.caliper_args = context.options.target_class

    if context.options.memory_profiling:
      self.caliper_args += ['--measureMemory']

    if context.options.debug:
      self.java_args.extend(context.config.getlist('jvm', 'debug_args'))
      self.caliper_args += ['--debug']

  def execute(self, targets):
    # For rewriting JDK classes to work, the JAR file has to be listed specifically in
    # the JAR manifest as something that goes in the bootclasspath.
    # The MANIFEST list a jar 'allocation.jar' this is why we have to rename it
    agent_tools_classpath = self._bootstrap_utils.get_jvm_build_tools_classpath(self._agent_bootstrap_tools)
    agent_jar = agent_tools_classpath[0]
    allocation_jar = os.path.join(os.path.dirname(agent_jar), "allocation.jar")

    # TODO(Steve Gury): Find a solution to avoid copying the jar every run and being resilient
    # to version upgrade
    shutil.copyfile(agent_jar, allocation_jar)
    os.environ['ALLOCATION_JAR'] = str(allocation_jar)

    benchmark_tools_classpath = self._bootstrap_utils.get_jvm_build_tools_classpath(self._benchmark_bootstrap_tools)

    exit_code = runjava_indivisible(
      jvmargs=self.java_args,
      classpath=self.classpath(benchmark_tools_classpath),
      main='com.google.caliper.Runner',
      opts=self.caliper_args,
      workunit_name='caliper'
    )
    if exit_code != 0:
      raise TaskError()
