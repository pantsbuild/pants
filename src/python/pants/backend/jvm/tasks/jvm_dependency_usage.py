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
    """Creates a graph of concrete targets, with their sum of products and dependencies.

    Synthetic targets contribute products and dependencies to their concrete target.
    """

    # Initialize all Nodes.
    classes_by_target = self.context.products.get_data('classes_by_target')
    product_deps_by_src = self.context.products.get_data('product_deps_by_src')
    nodes = dict()
    for target in targets:
      # Record the product count and used products for this target.
      products_total = sum(1 for _, paths in classes_by_target[target].rel_paths() for p in paths)
      outbound_edges = defaultdict(Edge)
      target_product_deps_by_src = product_deps_by_src.get(target, dict())
      for src in target.sources_relative_to_buildroot():
        for product_dep in target_product_deps_by_src.get(os.path.join(buildroot, src), []):
          for dep_tgt in self.targets_by_file.get(product_dep, []):
            if dep_tgt != target:
              outbound_edges[dep_tgt.concrete_derived_from].products_used.add(product_dep)

      # Create or extend a Node for the concrete version of this target.
      concrete_target = target.concrete_derived_from
      if concrete_target in nodes:
        node = nodes[concrete_target]
      else:
        node = nodes[concrete_target] = Node(concrete_target)
      node.add_derivation(target, products_total, outbound_edges)

    # Prune any Nodes with 0 products.
    for concrete_target, node in nodes.copy().items():
      if node.products_total == 0:
        nodes.pop(concrete_target)

    return DependencyUsageGraph(nodes, self.size_estimators[self.get_options().size_estimator])


class Node(object):
  def __init__(self, concrete_target):
    self.concrete_target = concrete_target
    self.products_total = 0
    self.derivations = set()
    # Dict mapping concrete dependency targets to an Edge object.
    self.dep_edges = defaultdict(Edge)

  def add_derivation(self, derived_target, derived_products, outbound_edges):
    self.derivations.add(derived_target)
    self.products_total += derived_products
    for dep, edge in outbound_edges.items():
      self.dep_edges[dep] += edge

  def __eq__(self, other):
    return self.concrete_target.address == other.concrete_target.address

  def __ne__(self, other):
    return not self.__eq__(other)

  def __hash_(self):
    return hash(self.concrete_target.address)


class Edge(object):
  def __init__(self):
    self.products_used = set()

  def __iadd__(self, that):
    self.products_used |= that.products_used
    return self


class DependencyUsageGraph(object):

  def __init__(self, nodes, size_estimator):
    self._nodes = nodes
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

  def to_json(self):
    res_dict = {}
    def gen_dep_edge(node, edge, dep_tgt):
      dep_tgt_products_total = max(self._nodes[dep_tgt].products_total if dep_tgt in self._nodes else 1, 1)
      return {
        'target': dep_tgt.address.spec,
        'products_used': len(edge.products_used),
        'products_used_ratio': 1.0 * len(edge.products_used) / dep_tgt_products_total
      }
    for node in self._nodes.values():
      res_dict[node.concrete_target.address.spec] = {
          'job_size': self._job_size(node.concrete_target),
          'job_size_transitive': self._trans_job_size(node.concrete_target),
          'products_total': node.products_total,
          'dependencies': [gen_dep_edge(node, edge, dep_tgt) for dep_tgt, edge in node.dep_edges.items()]
        }
    return json.dumps(res_dict, indent=2, sort_keys=True)
