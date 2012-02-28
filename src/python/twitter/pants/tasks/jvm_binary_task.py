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

from twitter.common.collections.orderedset import OrderedSet

from twitter.pants import is_internal
from twitter.pants.targets.jvm_binary import JvmBinary
from twitter.pants.tasks import Task


class JvmBinaryTask(Task):
  def __init__(self, context):
    Task.__init__(self, context)

  def is_binary(self, target):
    return isinstance(target, JvmBinary)

  def require_jar_dependencies(self):
    self.context.products.require('jar_dependencies', predicate=self.is_binary)

  def list_jar_dependencies(self, binary):
    jardepmap = self.context.products.get('jar_dependencies') or {}

    excludes = set()
    for exclude_key in ((e.org, e.name) if e.name else e.org for e in binary.deploy_excludes):
      exclude = jardepmap.get(exclude_key)
      if exclude:
        for basedir, jars in exclude.items():
          for jar in jars:
            excludes.add((basedir, jar))
    self.context.log.debug('Calculated excludes:\n\t%s' % '\n\t'.join(str(e) for e in excludes))

    externaljars = OrderedSet()
    def add_jars(target):
      mapped = jardepmap.get(target)
      if mapped:
        for basedir, jars in mapped.items():
          for externaljar in jars:
            if (basedir, externaljar) not in excludes:
              externaljars.add((basedir, externaljar))
            else:
              self.context.log.debug('Excluding %s from binary' % externaljar)

    binary.walk(add_jars, is_internal)
    return externaljars