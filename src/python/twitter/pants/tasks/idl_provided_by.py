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

from twitter.pants.targets import IdlJvmThriftLibrary, JavaThriftLibrary
from twitter.pants.tasks import Task


class IdlProvidedBy(Task):
  """ Replaces idl jar dependency with correct published jar

    Replaces this target with the jar specified via the constructor arg 'provided_by'
    in the dependency graph in the given context.  This is necessary if you are attempting
    to publish an artifact that depends on an IdlJvmThriftLibrary target, which doesn't
    provide an artifact directly.
  """

  def __init__(self, context):
    Task.__init__(self, context)
    self.context.products.require('java')

  def _cleanup_target(self, target, compiled_jar, idl_jar):
    for dependant in self.context.dependants(on_predicate=lambda tgt: tgt == target):
      if hasattr(dependant, 'replace_dependency'):
        if isinstance(dependant, JavaThriftLibrary):
          self.context.log.info(
            'Replacing %s with %s as dependency of %s' % (target, idl_jar, dependant))
          idl_jar.idl_only = True
          dependant.replace_dependency(target, idl_jar)
        else:
          self.context.log.info(
            'Replacing %s with %s as dependency of %s' % (target, compiled_jar, dependant))
          dependant.replace_dependency(target, compiled_jar)
    self.context.remove_target(target)

  def execute(self, targets):
    def process(target):
      compiled_jar = target.provided_by
      idl_jar = target.idl_jar
      self._cleanup_target(target, compiled_jar, idl_jar)
      genmap = self.context.products.get('java').get(target)
      if genmap:
        for _, java_targets in genmap.items():
          for java_target in java_targets:
            self._cleanup_target(java_target, compiled_jar, idl_jar)

    for target in targets:
      target.walk(process, predicate=lambda target: isinstance(target, IdlJvmThriftLibrary))
