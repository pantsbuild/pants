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
             help='Score all targets in the build graph transitively.')
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
    classes_by_target = self.context.products.get_data('classes_by_target')
    total_products_by_target = {
        target: sum(1 for _, paths in classes_by_target[target].rel_paths() for p in paths)
        for target in targets
      }

    graph = DependencyUsageGraph(self.size_estimators[self.get_options().size_estimator])

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

        if target.is_original and target not in graph:
          total_products = total_products_by_target[target]
          node = graph[target] = Node(target, total_products)

        total_dep_products = total_products_by_target[dep_tgt]
        if total_dep_products == 0:
          # The dep_tgt is a 3rd party library, so skip.
          continue
        num_dep_products_used = len(used_product_deps_by_target.get(dep_tgt, []))
        if dep_tgt.is_original:
          if dep_tgt not in graph:
            graph[dep_tgt] = Node(dep_tgt, total_dep_products)
          node.usage_by_dep[graph[dep_tgt]] = num_dep_products_used
        else:
          # The dep_tgt is synthetic -- so we want to attribute it's used / total products to
          # the target it was derived from, which may already exist as a dependency of node.
          original_dep_tgt = dep_tgt.derived_from
          if original_dep_tgt not in graph:
            graph[original_dep_tgt] = Node(original_dep_tgt, total_dep_products)
          else:
            graph[original_dep_tgt].total_products += total_dep_products
          node.usage_by_dep[graph[original_dep_tgt]] += num_dep_products_used

    return graph


class Node(object):

    def __init__(self, target, total_products):
      self.target = target
      self.total_products = total_products
      self.usage_by_dep = defaultdict(int)

    def __eq__(self, other):
      return self.target.address == other.target.address

    def __ne__(self, other):
      return not self.__eq__(other)

    def __hash_(self):
      return hash(self.target.address)


class DependencyUsageGraph(dict):

  def __init__(self, size_estimator):
    self._size_estimator = size_estimator
    self._job_size_cache = {}
    self._trans_job_size_cache = {}

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
    """Compute the min, max, and total products used by dependents of each node.

    Returns a dict mapping each node to a named tuple of (min_used, max_used, total_used).
    Note: this is an aggregation of inbound edges.
    """
    UsageStats = namedtuple('UsageStats', ['min_used', 'max_used', 'total_used'])
    usage_stats_by_node = defaultdict(lambda: UsageStats(0, 0, 0))
    for _, node in self.items():
      for dep_node, products_used in node.usage_by_dep.items():
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
      avg_products_used = 1.0 * usage_stats.total_used / max(inbound_edges, 1)
      res_dict[node.target.address.spec] = {
          'job_size': self._job_size(node.target),
          'trans_job_size': self._trans_job_size(node.target),
          'inbound_edges': inbound_edges,
          'min_products_used': usage_stats.min_used,
          'max_products_used': usage_stats.max_used,
          'avg_products_used': avg_products_used,
          'total_products': node.total_products,
          'avg_ratio': avg_products_used / max(node.total_products, 1),
          'dependencies': [{
              'target': dep_node.target.address.spec,
              'products_used': products_used,
              'total_products': dep_node.total_products,
              'ratio': 1.0 * products_used / max(dep_node.total_products, 1),
            } for dep_node, products_used in node.usage_by_dep.items()]
        }
    return json.dumps(res_dict, indent=2, sort_keys=True)
