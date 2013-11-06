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
# ===================================================================================================

from functools import partial

from twitter.pants.tasks import TaskError, Task


class BootstrapJvmTools(Task):

  def __init__(self, context):
    super(BootstrapJvmTools, self).__init__(context)
    context.products.require_data('jvm_build_tools')

  def execute(self, targets):
    context = self.context
    if context.products.is_required_data('jvm_build_tools_classpath_callbacks'):
      deplist_map = context.products.get('jvm_build_tools').get('jvm_build_tools')
      callback_map = context.products.get('jvm_build_tools_classpath_callbacks')
      # We leave a callback in the products map because we want these Ivy calls 
      # to be done lazily (they might never actually get executed) and we want
      # to hit Task.invalidated (called in Task.ivy_resolve) on the instance of 
      # BootstrapJvmTools rather than the instance of whatever class requires
      # the bootstrap tools.  It would be awkward and possibly incorrect to call
      # self.invalidated twice on a Task that does meaningful invalidation on its
      # targets. -pl
      for key, deplist in deplist_map.items():
        callback_map.add('jvm_build_tools_classpath_callbacks',
                         key,
                         [partial(self.bootstrap_classpath, tools=deplist)])

  def resolve_tool_targets(self, tools):
    if not tools:
      self.context.log.warn("BootstrapJvmTools.resolve_tool_targets called with no tool"
                            " dependency addresses.  This probably means that you don't"
                            " have an entry in your pants.ini for this tool.")
    for tool in tools:
      try:
        targets = list(self.context.resolve(tool))
        if not targets:
          raise KeyError
      except KeyError:
        self.context.log.error("Failed to resolve target for bootstrap tool: %s."
                               "  You probably need to add this dep to your"
                               " tools build file(s), usually located in the root of the build." % 
                               tool)
        raise
      for target in targets:
        yield target

  def bootstrap_classpath(self, tools, java_runner=None):
    targets = list(self.resolve_tool_targets(tools))
    ivy_args = [
      '-sync',
      '-symlink',
      '-types', 'jar', 'bundle',
    ]
    return self.ivy_resolve(targets, java_runner=java_runner, ivy_args=ivy_args)
