# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import json
import os
from collections import defaultdict, namedtuple

from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.tasks.jvm_compile.jvm_compile_isolated_strategy import create_size_estimators
from pants.backend.jvm.tasks.jvm_dependency_analyzer import JvmDependencyAnalyzer
from pants.base.build_environment import get_buildroot
from pants.util.fileutil import create_size_estimators


class JvmDependencyUsage(JvmDependencyAnalyzer):
  """Determines the dependency usage ratios of targets.

  Analyzes the relationship between the products a target T produces vs. the products
  which T's dependents actually require (this is done by observing analysis files).
  If the ratio of required products to available products is low, then this is a sign
  that target T isn't factored well.

  A graph is formed from these results, where each node of the graph is a target, and
  each edge is a product usage ratio between a target and its dependency. The nodes
  also contain additional information to guide refactoring -- for example, the estimated
  job size of each target, which indicates the impact a poorly factored target has on
  the build times. (see DependencyUsageGraph->to_json)

  The graph is outputted into a JSON file, with the intent of consuming and analyzing
  the graph via some external tool.
  """

  size_estimators = create_size_estimators()

  @classmethod
  def register_options(cls, register):
    super(JvmDependencyUsage, cls).register_options(register)
    register('--size-estimator',
             choices=list(cls.size_estimators.keys()), default='filesize',
             help='The method of target size estimation.')
    register('--transitive', default=True, action='store_true',
             help='Score all targets in build graph transitively.')
    register('--output-file', type=str,
             help='Output dependency usage graph as JSON to the specified file.')

  def execute(self):
    if self.get_options().skip:
      return
    targets = (self.context.targets() if self.get_options().transitive
               else self.context.target_roots)
    graph = self.create_dep_usage_graph(targets, get_buildroot())
    output_file = self.get_options().output_file
    if output_file:
      self.context.log.info('Writing dependency usage graph to {}'.format(output_file))
      with open(output_file, 'w') as fh:
        fh.write(graph.to_json())
    else:
      self.context.log.error('No output file specified')

  def create_dep_usage_graph(self, targets, buildroot):
    graph = DependencyUsageGraph(self.size_estimators[self.get_options().size_estimator])
    classes_by_target = self.context.products.get_data('classes_by_target')
    for target in targets:
      product_deps_by_src = self.context.products.get_data('product_deps_by_src').get(target)
      if product_deps_by_src is None:
        self.context.log.warn('No dependency analysis for {}'.format(target.address.spec))
        continue

      # Maps some dependency target d to the exact products of d which are used by :param target:
      used_product_deps_by_target = defaultdict(set)
      for src in target.sources_relative_to_buildroot():
        abs_src = os.path.join(buildroot, src)
        for product_dep in product_deps_by_src.get(abs_src, []):
          dep_tgts = self.targets_by_file.get(product_dep)
          if dep_tgts is None:
            # product_dep is from JVM runtime / bootstrap jar, so skip.
            continue
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

        used_products = len(used_product_deps_by_target.get(dep_tgt, []))
        total_products = sum(1 for _, paths in classes_by_target[dep_tgt].rel_paths() for p in paths)
        if total_products == 0:
          # The dep_tgt is a 3rd party library, so skip.
          continue

        node = graph[target]
        if dep_tgt.is_original:
          node.add_dep(graph[dep_tgt], used_products, total_products)
        else:
          # The dep_tgt is synthetic -- so we want to attribute it's used / total products to
          # the target it was derived from, which may already exist as a dependency of node.
          node.update_dep(graph[dep_tgt.derived_from], used_products, total_products)

    return graph


class DependencyUsageGraph(dict):

  class Node(object):

    def __init__(self, target):
      self.target = target
      # Maps dep node to tuple of (products used, products total) of said dep node.
      self.usage_by_dep = defaultdict(lambda: (0, 0))

    def add_dep(self, node, products_used, products_total):
      self.usage_by_dep[node] = (products_used, products_total)

    def update_dep(self, node, products_used, products_total):
      old_products_used, old_products_total = self.usage_by_dep[node]
      self.usage_by_dep[node] = (old_products_used + products_used,
                                 old_products_total + products_total)

    def __eq__(self, other):
      return self.target.address == other.target.address

    def __ne__(self, other):
      return not self.__eq__(other)

    def __hash_(self):
      return hash(self.target.address)

  def __init__(self, size_estimator):
    self._size_estimator = size_estimator
    self._job_size_cache = {}
    self._trans_job_size_cache = {}

  def __missing__(self, target):
    node = self[target] = self.Node(target)
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

  def _aggregate_product_usage_stats(self):
    """Compute the min, max, and total products used for each node in the current graph.

    Returns a dict mapping each node to a named tuple of (min_used, max_used, total_used).
    """
    UsageStats = namedtuple('UsageStats', ['min_used', 'max_used', 'total_used'])
    usage_stats_by_node = defaultdict(lambda: UsageStats(0, 0, 0))
    for _, node in self.items():
      for dep_node, (products_used, _) in node.usage_by_dep.items():
        if dep_node not in usage_stats_by_node:
          usage_stats_by_node[dep_node] = UsageStats(products_used, products_used, products_used)
        else:
          old = usage_stats_by_node[dep_node]
          usage_stats_by_node[dep_node] = UsageStats(min(old.min_used, products_used),
                                                     max(old.max_used, products_used),
                                                     old.total_used + products_used)
    return usage_stats_by_node

  def to_json(self):
    res_dict = {}
    usage_stats_by_node = self._aggregate_product_usage_stats()
    for _, node in self.items():
      usage_stats = usage_stats_by_node[node]
      inbound_edges = len(node.target.dependents)
      res_dict[node.target.address.spec] = {
          'job_size': self._job_size(node.target),
          'trans_job_size': self._trans_job_size(node.target),
          'inbound_edges': inbound_edges,
          'min_products_used': usage_stats.min_used,
          'max_products_used': usage_stats.max_used,
          'avg_products_used': 1.0 * usage_stats.total_used / max(inbound_edges, 1),
          'dependencies': [{
              'target': dep_node.target.address.spec,
              'products_used': products_used,
              'products_total': products_total,
              'ratio': 1.0 * products_used / max(products_total, 1),
            } for dep_node, (products_used, products_total) in node.usage_by_dep.items()]
        }
    return json.dumps(res_dict, indent=2, sort_keys=True)
