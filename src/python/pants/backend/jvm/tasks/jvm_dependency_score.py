# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import json
import os
from collections import defaultdict

from pants.backend.jvm.targets.jar_library import JarLibrary
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
    register('--root-targets-only', default=True,
             help='Score only the root targets, not their dependencies.')
    register('--output-file', type=str,
             help='Output score graph as JSON to this file, creating the file if necessary. '
                  'If no file specified, score graph is outputted to stdout.')

  def execute(self):
    if self.get_options().skip:
      return
    targets = (self.context.target_roots if self.get_options().root_targets_only
               else self.context.targets())
    self.score(targets)

  def score(self, targets):
    graph = DepScoreGraph(self.size_estimators[self.get_options().size_estimator])

    for target in targets:
      actual_source_deps = self.context.products.get_data('actual_source_deps').get(target)
      if actual_source_deps is None:
        # No analysis for this target -- skip it.
        continue

      # Maps some target t to the exact sources of t which are used by :param target:
      used_src_deps_by_target = defaultdict(set)
      abs_srcs = [os.path.join(get_buildroot(), src)
                  for src in target.sources_relative_to_buildroot()]
      for src in abs_srcs:
        for src_dep in actual_source_deps.get(src, []):
          dep_tgts = self.targets_by_file.get(src_dep)
          if dep_tgts is None:
            # src_dep is from JVM runtime / bootstrap jar, so skip.
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

      for dep_tgt in target.dependencies:
        if (dep_tgt == target
            or dep_tgt in targets_with_derivation
            or isinstance(dep_tgt, JarLibrary)):
          continue

        actual_source_deps = used_src_deps_by_target.get(dep_tgt, [])
        total_srcs = len(dep_tgt.sources_relative_to_buildroot())
        if total_srcs == 0:
          continue
        percent_used = 100.0 * len(actual_source_deps) / total_srcs

        graph[target].add_child(graph[dep_tgt], percent_used)

    output_file = self.get_options().output_file
    if output_file:
      with open(output_file, 'w') as fh:
        fh.write(graph.to_json())
    else:
      graph.log_usage(self.context.log)


class DepScoreGraph(dict):

  class Node(object):

    def __init__(self, target, job_size):
      self.target = target
      self.job_size = job_size
      # Maps child node to percent used of child node's target.
      self.children = {}

    def add_child(self, node, percent_used):
      self.children[node] = percent_used

    def __eq__(self, other):
      return self.target == other.target

    def __hash_(self):
      return hash(self.target)

  def __init__(self, size_estimator):
    self._size_estimator = size_estimator
    self._job_size_cache = {}

  def __missing__(self, target):
    node = self[target] = self.Node(target, self._job_size(target))
    return node

  def _job_size(self, target):
    if target not in self._job_size_cache:
      dep_sum = sum(self._job_size(dep) for dep in target.dependencies)
      self._job_size_cache[target] = \
          self._size_estimator(target.sources_relative_to_buildroot()) + dep_sum
    return self._job_size_cache[target]

  def log_usage(self, log):
    for _, node in self.items():
      log.info('Dependency usage for ' + node.target.address.spec_path)
      for child_node, percent_used in node.children.items():
        log_fn = log.error if percent_used == 0 else log.info
        log_fn('\t{target} --> {percent}%, job size: {size}'
               .format(target=child_node.target.address.spec_path,
                       percent=percent_used,
                       size=child_node.job_size))

  def to_json(self):
    res_dict = {}
    for _, node in self.items():
      res_dict[node.target.address.spec_path] = [{
          'target': child_node.target.address.spec_path,
          'job_size': child_node.job_size,
          'percent_used': percent_used,
        } for child_node, percent_used in node.children.items()]
    return json.dumps(res_dict, indent=2)
