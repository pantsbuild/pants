# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os.path
from collections import defaultdict

from pants.base.build_environment import get_buildroot
from pants.backend.core.tasks.task import Task


class CodeGen(Task):
  """Encapsulates the common machinery for codegen targets that support multiple output languages.

  This Task will only invoke code generation for changed targets and for the set of languages
  in the active context that require codegen unless forced.
  """

  @classmethod
  def package_path(cls, package):
    """Return the package name translated into a path"""
    return package.replace('.', os.sep)

  @classmethod
  def product_types(cls):
    return ['java', 'scala']

  def is_gentarget(self, target):
    """Subclass must return True if it handles generating for the target."""
    raise NotImplementedError

  def is_forced(self, lang):
    """Subclass may return True to force code generation for the given language."""
    return False

  def genlangs(self):
    """Subclass must use this to identify the targets consuming each language it generates for.

    Return value is a dict mapping supported generation target language names
    to a predicate that can select targets consuming that language.
    """
    raise NotImplementedError

  def prepare_gen(self, targets):
    """
      Subclasses should override if they need to prepare for potential upcoming calls to genlang.

      Note that this does not mean genlang will necessarily be called.
    """
    pass

  def genlang(self, lang, targets):
    """Subclass must override and generate code in :lang for the given targets.

    May return a list of pairs (target, files) where files is a list of files
    to be cached against the target.
    """
    raise NotImplementedError

  def createtarget(self, lang, gentarget, dependees):
    """Subclass must override and create a synthetic target.

     The target must contain the sources generated for the given gentarget.
    """
    raise NotImplementedError

  def getdependencies(self, gentarget):
    return gentarget.dependencies

  def updatedependencies(self, target, dependency):
    target.inject_dependency(dependency.address)

  def prepare(self, round_manager):
    round_manager.require_data('jvm_build_tools_classpath_callbacks')

  def execute(self):
    gentargets = self.context.targets(self.is_gentarget)
    capabilities = self.genlangs() # lang_name => predicate
    gentargets_by_dependee = self.context.dependents(
      on_predicate=self.is_gentarget,
      from_predicate=lambda t: not self.is_gentarget(t)
    )
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
      self.context.log.warn('Left with unexpected unconsumed gen targets:\n\t%s' % '\n\t'.join(
        '%s -> %s' % (dependee, gentargets)
        for dependee, gentargets in gentargets_by_dependee.items()
      ))

    if gentargets:
      self.prepare_gen(gentargets)
      with self.invalidated(gentargets, invalidate_dependents=True) as invalidation_check:
        for vts in invalidation_check.invalid_vts_partitioned:
          invalid_targets = set(vts.targets)
          for lang, tgts in gentargets_bylang.items():
            invalid_lang_tgts = invalid_targets.intersection(tgts)
            if invalid_lang_tgts:
              self.genlang(lang, invalid_lang_tgts)

      # Link synthetic targets for all in-play gen targets.
      invalid_vts_by_target = dict([(vt.target, vt) for vt in invalidation_check.invalid_vts])
      vts_artifactfiles_pairs = []
      write_to_artifact_cache = (self.artifact_cache_writes_enabled() if invalid_vts_by_target
                                 else False)
      for lang, tgts in gentargets_bylang.items():
        if tgts:
          langtarget_by_gentarget = {}
          for target in tgts:
            syn_target = self.createtarget(
              lang,
              target,
              dependees_by_gentarget.get(target, [])
            )
            syn_target.add_labels('codegen')
            if write_to_artifact_cache and target in invalid_vts_by_target:
              generated_sources = [os.path.join(get_buildroot(), path)
                                   for path in syn_target.sources_relative_to_buildroot()]
              vts_artifactfiles_pairs.append((invalid_vts_by_target[target], generated_sources))
            langtarget_by_gentarget[target] = syn_target
          genmap = self.context.products.get(lang)
          for gentarget, langtarget in langtarget_by_gentarget.items():
            genmap.add(gentarget, get_buildroot(), [langtarget])
            # Transfer dependencies from gentarget to its synthetic counterpart.
            for dep in self.getdependencies(gentarget):
              if self.is_gentarget(dep):  # Translate the dep to its synthetic counterpart.
                self.updatedependencies(langtarget, langtarget_by_gentarget[dep])
              else:  # Depend directly on the dep.
                self.updatedependencies(langtarget, dep)
      if write_to_artifact_cache:
        self.update_artifact_cache(vts_artifactfiles_pairs)
