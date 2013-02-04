# ==================================================================================================
# Copyright 2012 Twitter, Inc.
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

__author__ = 'John Sirois'

import os

from twitter.pants import get_buildroot, is_test
from twitter.pants.targets import JvmTarget
from twitter.pants.tasks import Task

class JvmTask(Task):
  def classpath(self, cp=None, confs=None):
    classpath = cp or []
    with self.context.state('classpath', []) as cp:
      classpath.extend(jar for conf, jar in cp if not confs or conf in confs)

    # TODO(John Sirois): Fixup jvm test targets to declare their resources and fixup resources to
    # be their own target libraries or tests then depend on:
    # http://jira.local.twitter.com/browse/AWESOME-108
    bases = set()
    for target in self.context.targets():
      if isinstance(target, JvmTarget) and (is_test(target) or hasattr(target, 'resources')):
        sibling_resources_base = os.path.join(os.path.dirname(target.target_base), 'resources')
        if sibling_resources_base not in bases:
          sibling_resources_full_path = os.path.join(get_buildroot(), sibling_resources_base)
          if os.path.isdir(sibling_resources_full_path):
            classpath.append(sibling_resources_full_path)
          bases.add(sibling_resources_base)

    return classpath
