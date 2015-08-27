# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from collections import defaultdict

from pants.backend.jvm.tasks.jvm_dependency_analyzer import JvmDependencyAnalyzer
from pants.base.build_environment import get_buildroot


class JvmDependencyScore(JvmDependencyAnalyzer):

  def execute(self):
    if self.get_options().skip:
      return
    for target in self.context.target_roots:
      actual_source_deps = self.context.products.get_data('actual_source_deps').get(target)
      if actual_source_deps is not None:
        self.score(target, actual_source_deps)

  def score(self, target, src_deps):
    # Maps some target t to the exact sources of t which are used by :param target:
    used_src_deps_by_target = defaultdict(set)
    with self.context.new_workunit(name='score-target-usage'):
      abs_srcs = [os.path.join(get_buildroot(), src)
                  for src in target.sources_relative_to_buildroot()]
      for src in abs_srcs:
        for src_dep in src_deps.get(src, []):
          dep_tgts = self.targets_by_file.get(src_dep)
          if dep_tgts is None:
            # TODO(cgibb): Why is this None for jars?
            # self.context.log.warn('no target for ' + src_dep)
            pass
          else:
            for tgt in dep_tgts:
              used_src_deps_by_target[tgt].add(src_dep)

      # Skip targets that generate into other targets (like JavaAntlrLibrary) because
      # only the dependency to the generated target will be parsed from analysis file.
      targets_with_derivation = set()
      for dep_tgt in target.dependencies:
        if dep_tgt.derived_from != dep_tgt:
          targets_with_derivation.add(dep_tgt.derived_from)

      self.context.log.warn('Dependency usage for {}'.format(target.address.spec_path))
      for dep_tgt in target.dependencies:
        if dep_tgt == target or dep_tgt in targets_with_derivation:
          continue
        used_src_deps = used_src_deps_by_target.get(dep_tgt, [])
        total_srcs = len(dep_tgt.sources_relative_to_buildroot())
        if total_srcs > 0:
          percent_used = 100.0 * len(used_src_deps) / total_srcs
          log_fn = (self.context.log.error if percent_used == 0
                    else self.context.log.warn if percent_used < 50
                    else self.context.log.info)
          log_fn('\t{target} --> {percent_used}%'
                 .format(target=dep_tgt.address.spec_path, percent_used=percent_used))
        else:
          # TODO(cgibb): Why is total_srcs always 0 for jars?
          # self.context.log.warn('\tno sources for ' + dep_tgt.address.spec_path + ', used = ' + str(used_src_deps))
          pass
