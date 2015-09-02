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
             help='Output score graph as JSON to the specified file.')

  def execute(self):
    if self.get_options().skip:
      return
    targets = (self.context.target_roots if self.get_options().root_targets_only
               else self.context.targets())
    self.score(targets)

  def score(self, targets):
    graph = DepScoreGraph(self.size_estimators[self.get_options().size_estimator])

    classes_by_target = self.context.products.get_data('classes_by_target')
    for target in targets:
      product_deps_by_src = self.context.products.get_data('actual_source_deps').get(target)
      if product_deps_by_src is None:
        # No analysis for this target -- skip it.
        continue

      # Maps some dependency target d to the exact products of d which are used by :param target:
      used_product_deps_by_target = defaultdict(set)
      abs_srcs = [os.path.join(get_buildroot(), src)
                  for src in target.sources_relative_to_buildroot()]
      for src in abs_srcs:
        for product_dep in product_deps_by_src.get(src, []):
          dep_tgts = self.targets_by_file.get(product_dep)
          if dep_tgts is None:
            # product_dep is from JVM runtime / bootstrap jar, so skip.
            pass
          else:
            for tgt in dep_tgts:
              used_product_deps_by_target[tgt].add(product_dep)

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

        used_product_deps = used_product_deps_by_target.get(dep_tgt, [])
        total_products = list(p for _, paths in classes_by_target[dep_tgt].rel_paths() for p in paths)
        if not total_products:
          continue
        graph[target].add_child(graph[dep_tgt], len(used_product_deps), len(total_products))

    output_file = self.get_options().output_file
    if output_file:
      self.context.log.info('Writing dependency score graph to {}'.format(output_file))
      with open(output_file, 'w') as fh:
        fh.write(graph.to_json())
    else:
      self.context.log.error('No output file specified')

class DepScoreGraph(dict):

  class Node(object):

    def __init__(self, target, job_size, trans_job_size):
      self.target = target
      self.inbound_edges = len(target.dependents)
      self.job_size = job_size
      self.trans_job_size = trans_job_size
      self.min_products_used = None
      self.max_products_used = None
      self.products_used_count = 0
      # Maps child node to percent used of child node's target.
      self.children = {}

    def add_child(self, node, products_used, products_total):
      def get_update(f, n):
        return f(n, products_used) if n is not None else products_used
      node.min_products_used = get_update(min, node.min_products_used)
      node.max_products_used = get_update(max, node.max_products_used)
      node.products_used_count += products_used
      self.children[node] = (products_used, products_total)

    def __eq__(self, other):
      return self.target == other.target

    def __hash_(self):
      return hash(self.target)

  def __init__(self, size_estimator):
    self._size_estimator = size_estimator
    self._job_size_cache = {}
    self._trans_job_size_cache = {}

  def __missing__(self, target):
    node = self[target] = self.Node(target, self._job_size(target), self._trans_job_size(target))
    return node

  def _job_size(self, target):
    if target not in self._job_size_cache:
      self._job_size_cache[target] = self._size_estimator(target.sources_relative_to_buildroot())
    return self._job_size_cache[target]

  def _trans_job_size(self, target):
    if target not in self._trans_job_size_cache:
      dep_sum = sum(self._trans_job_size(dep) for dep in target.dependencies)
      self._trans_job_size_cache[target] = self._job_size(target) + dep_sum
    return self._trans_job_size_cache[target]

  def to_json(self):
    res_dict = {}
    for _, node in self.items():
      res_dict[node.target.address.spec] = {
          'synthetic': node.target.is_synthetic,
          'job_size': node.job_size,
          'trans_job_size': node.trans_job_size,
          'inbound_edges': node.inbound_edges,
          'min_products_used': node.min_products_used,
          'max_products_used': node.max_products_used,
          'avg_products_used': 1.0 * node.products_used_count / max(node.inbound_edges, 1),
          'dependencies': [{
              'target': child_node.target.address.spec,
              'products_used': products_used,
              'products_total': products_total,
              'ratio': 1.0 * products_used / max(products_total, 1),
            } for child_node, (products_used, products_total) in node.children.items()]
        }
    return json.dumps(res_dict, indent=2)
