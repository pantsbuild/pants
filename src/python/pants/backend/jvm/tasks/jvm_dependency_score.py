# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from collections import defaultdict

from pants.backend.jvm.tasks.jvm_dependency_analyzer import JvmDependencyAnalyzer
from pants.base.build_environment import get_buildroot


def create_size_estimators():
  def line_count(filename):
    with open(filename, 'rb') as fh:
      return sum(1 for line in fh)
  return {
    'linecount': lambda srcs: sum(linecount(src) for src in srcs),
    'filecount': lambda srcs: len(srcs),
    'filesize': lambda srcs: sum(os.path.getsize(src) for src in srcs),
    'nosize': lambda srcs: 0,
  }


class JvmDependencyScore(JvmDependencyAnalyzer):

  size_estimators = create_size_estimators()

  @classmethod
  def register_options(cls, register):
    super(JvmDependencyScore, cls).register_options(register)
    register('--size-estimator',
             choices=list(cls.size_estimators.keys()), default='filesize',
             help='The method of target size estimation.')
    register('--root-targets-only', default=False,
             help='Score only the root targets, not their dependencies.')

  def execute(self):
    if self.get_options().skip:
      return
    self._size_estimator = self.size_estimators[self.get_options().size_estimator]
    targets = (self.context.target_roots if self.get_options().root_targets_only
               else self.context.targets())
    self.score(targets)

  def _job_size(self, target, job_size_cache):
    if target not in job_size_cache:
      dep_sum = sum(self._job_size(dep, job_size_cache) for dep in target.dependencies)
      job_size_cache[target] = \
          self._size_estimator(target.sources_relative_to_buildroot()) + dep_sum
    return job_size_cache[target]

  def score(self, targets):
    # Maps target --> job size.
    job_size_cache = {}
    for target in targets:
      actual_source_deps = self.context.products.get_data('actual_source_deps').get(target)
      if actual_source_deps is None:
        # No analysis for this target -- skip it.
        continue

      # Maps some target t to the exact sources of t which are used by :param target:
      used_src_deps_by_target = defaultdict(set)
      with self.context.new_workunit(name='score-target-usage'):
        abs_srcs = [os.path.join(get_buildroot(), src)
                    for src in target.sources_relative_to_buildroot()]
        for src in abs_srcs:
          for src_dep in actual_source_deps.get(src, []):
            dep_tgts = self.targets_by_file.get(src_dep)
            if dep_tgts is None:
              # TODO(cgibb): Why is this None for jars?
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

        self.context.log.info('Dependency usage for {}'.format(target.address.spec_path))
        for dep_tgt in target.dependencies:
          if dep_tgt == target or dep_tgt in targets_with_derivation:
            continue

          actual_source_deps = used_src_deps_by_target.get(dep_tgt, [])
          total_srcs = len(dep_tgt.sources_relative_to_buildroot())
          if total_srcs == 0:
            # TODO(cgibb): Why is total_srcs always 0 for jars?
            continue
          percent_used = 100.0 * len(actual_source_deps) / total_srcs

          log_fn = (self.context.log.error if percent_used == 0
                    else self.context.log.warn if percent_used < 25
                    else self.context.log.info)
          log_fn('\t{target} (job size: {size}) --> {percent_used}% (files imported / available)'
                 .format(target=dep_tgt.address.spec_path,
                         percent_used=percent_used,
                         size=self._job_size(dep_tgt, job_size_cache)))
