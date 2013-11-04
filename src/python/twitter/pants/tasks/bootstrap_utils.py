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


class BootstrapUtils(object):

  def __init__(self, products):
    self._products = products

  def get_jvm_build_tools_classpath(self, tools, java_runner=None):
    tools_tuple = tuple(sorted(tools))
    callbacks_map = (self._products.get('jvm_build_tools_classpath_callbacks')
                                   .get('jvm_build_tools_classpath_callbacks'))
    return callbacks_map.get(tools_tuple)[0](java_runner=java_runner)

  def register_all(self, toolsets):
    for toolset in toolsets:
      self.register_jvm_build_tools(toolset)

  def register_jvm_build_tools(self, tools):
    tools_tuple = tuple(sorted(tools))
    deplist_map = self._products.get('jvm_build_tools')
    self._products.require_data('jvm_build_tools_classpath_callbacks')
    if not deplist_map.add('jvm_build_tools', tools_tuple):
      deplist_map.add('jvm_build_tools', tools_tuple, tools_tuple)

