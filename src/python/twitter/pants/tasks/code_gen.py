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

from collections import defaultdict

from twitter.pants.tasks import Task, TaskError

class CodeGen(Task):
  """
    Encapsulates the common machinery for codegen targets that support multiple output languages.
    This Task will only invoke code generation for changed targets and for the set of languages
    in the active context that require codegen unless forced.
  """

  def is_gentarget(self, target):
    """
      Subclasses must override and return True if the target is a target it handles generating
      code for.
    """
    raise NotImplementedError

  def is_forced(self, lang):
    """
      Subclasses should override and return True if they wish to force code generation for the
      given language.
    """
    return False

  def genlangs(self):
    """
      Subclasses must override and return a dict mapping supported generation target language names
      to a predicate that can select targets consuming that language.
    """
    raise NotImplementedError

  def genlang(self, lang, targets):
    """
      Subclasses must override and generate code in :lang for the given targets.
    """
    raise NotImplementedError

  def createtarget(self, lang, gentarget, dependees):
    """
      Subclasses must override and create a synthetic target containing the sources generated for
      the given :gentarget.
    """
    raise NotImplementedError

  def getdependencies(self, gentarget):
    # TODO(John Sirois): fix python/jvm dependencies handling to be uniform
    if hasattr(gentarget, 'internal_dependencies'):
      return gentarget.internal_dependencies
    else:
      return gentarget.dependencies

  def updatedependencies(self, target, dependency):
    if hasattr(target, 'update_dependencies'):
      target.update_dependencies([dependency])
    else:
      target.dependencies.add(dependency)

  def execute(self, targets):
    gentargets = [t for t in targets if self.is_gentarget(t)]
    capabilities = self.genlangs() # lang_name => predicate

    gentargets_by_dependee = self.context.dependants(self.is_gentarget)
    dependees_by_gentarget = defaultdict(set)
    for dependee, tgts in gentargets_by_dependee.items():
      for gentarget in tgts:
        dependees_by_gentarget[gentarget].add(dependee)

    def find_gentargets(predicate):
      tgts = set()
      for dependee in gentargets_by_dependee.keys():
        if predicate(dependee):
          for tgt in gentargets_by_dependee.pop(dependee):
            tgt.walk(tgts.add, self.is_gentarget)
      return tgts.intersection(set(gentargets))

    gentargets_bylang = {}
    for lang, predicate in capabilities.items():
      gentargets_bylang[lang] = gentargets if self.is_forced(lang) else find_gentargets(predicate)

    if gentargets_by_dependee:
      raise TaskError('Left with unexpected unconsumed gen targets: %s' % gentargets_by_dependee)

    with self.changed(gentargets, invalidate_dependants=True) as changed_targets:
      changed = set(changed_targets)
      for lang, tgts in gentargets_bylang.items():
        lang_changed = changed.intersection(tgts)
        if lang_changed:
          self.genlang(lang, lang_changed)

    # Link synthetic targets for all in-play gen targets
    for lang, tgts in gentargets_bylang.items():
      if tgts:
        langtarget_by_gentarget = {}
        for target in tgts:
          langtarget_by_gentarget[target] = self.createtarget(
            lang,
            target,
            dependees_by_gentarget.get(target, [])
          )
        for gentarget, langtarget in langtarget_by_gentarget.items():
          for dep in self.getdependencies(gentarget):
            self.updatedependencies(langtarget, langtarget_by_gentarget[dep])
