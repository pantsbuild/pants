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

from twitter.pants import get_buildroot
from twitter.pants.tasks import Task

class JvmTask(Task):
  def classpath(self, cp=None, confs=None):
    classpath = cp or []
    with self.context.state('classpath', []) as cp:
      classpath.extend(jar for conf, jar in cp if not confs or conf in confs)

    # TODO(John Sirois): undo cheeseball! - derive src/resources from target attribute and then
    # later fix tests to declare their resources as well?
    classpath.extend(os.path.join(get_buildroot(), path)
                     for path in ('src/resources', 'tests/resources'))

    return classpath
