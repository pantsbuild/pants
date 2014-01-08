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

from twitter.pants.tasks.task_error import TaskError


class JvmToolBootstrapper(object):
  def __init__(self, products):
    self._products = products

  def get_jvm_tool_classpath(self, key, java_runner=None):
    """Get a callback to resolve the targets previously registered under the key."""
    callback_product_map = self._products.get_data('jvm_build_tools_classpath_callbacks') or {}
    callback = callback_product_map.get(key)
    if not callback:
      raise TaskError('No bootstrap callback registered for %s' % key)
    return callback(java_runner=java_runner)

  def register_jvm_tool(self, key, tools):
    """Register a list of targets against a key.

    We can later use this key to get a callback that will resolve these targets.
    Note: Not reentrant. We assume that all registration is done in the main thread.
    """
    self._products.require_data('jvm_build_tools_classpath_callbacks')
    tool_product_map = self._products.get_data('jvm_build_tools') or {}
    existing = tool_product_map.get(key)
    # It's OK to re-register with the same value, but not to change the value.
    if existing is not None:
      if existing != tools:
        raise TaskError('Attemping to change tools under %s from %s to %s.' % (key, existing, tools))
    else:
      tool_product_map[key] = tools
      self._products.set_data('jvm_build_tools', tool_product_map)

