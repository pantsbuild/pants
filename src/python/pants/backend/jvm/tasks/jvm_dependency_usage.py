# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import json
import os
import sys
from collections import OrderedDict, defaultdict, namedtuple

from pants.backend.core.targets.dependencies import Dependencies
from pants.backend.core.targets.resources import Resources
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.tasks.jvm_dependency_analyzer import JvmDependencyAnalyzer
from pants.base.build_environment import get_buildroot
from pants.build_graph.target import Target
from pants.util.dirutil import fast_relpath
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

  The graph is either summarized for local analysis or outputted as a JSON file for
  aggregation and analysis on a larger scale.
  """

  size_estimators = create_size_estimators()

  @classmethod
  def register_options(cls, register):
    super(JvmDependencyUsage, cls).register_options(register)
    register('--internal-only', default=True, action='store_true',
             help='Specifies that only internal dependencies should be included in the graph '
                  'output (no external jars).')
    register('--summary', default=True, action='store_true',
             help='When set, outputs a summary of the "worst" dependencies; otherwise, '
                  'outputs a JSON report.')
    register('--size-estimator',
             choices=list(cls.size_estimators.keys()), default='filesize',
             help='The method of target size estimation.')
    register('--transitive', default=True, action='store_true',
             help='Score all targets in the build graph transitively.')
    register('--output-file', type=str,
             help='Output destination. When unset, outputs to <stdout>.')

  @classmethod
  def prepare(cls, options, round_manager):
    super(JvmDependencyUsage, cls).prepare(options, round_manager)
    if not options.skip:
      round_manager.require_data('classes_by_source')
      round_manager.require_data('classes_by_target')
      round_manager.require_data('product_deps_by_src')

  def execute(self):
    if self.get_options().skip:
      return
    targets = (self.context.targets() if self.get_options().transitive
               else self.context.target_roots)
    graph = self.create_dep_usage_graph(targets, get_buildroot())
    output_file = self.get_options().output_file
    if output_file:
      self.context.log.info('Writing dependency usage to {}'.format(output_file))
      with open(output_file, 'w') as fh:
        self._render(graph, fh)
    else:
      sys.stdout.write('\n')
      self._render(graph, sys.stdout)

  def _render(self, graph, fh):
    chunks = graph.to_summary() if self.get_options().summary else graph.to_json()
    for chunk in chunks:
      fh.write(chunk)
    fh.flush()

  def _resolve_aliases(self, target):
    """Recursively resolve `target` aliases."""
    for declared in target.dependencies:
      if isinstance(declared, Dependencies) or type(declared) == Target:
        for r in self._resolve_aliases(declared):
          yield r
      else:
        yield declared

  def _is_declared_dep(self, target, dep):
    """Returns true if the given dep target should be considered a declared dep of target."""
    return dep in self._resolve_aliases(target)

  def _select(self, target):
    if self.get_options().internal_only and isinstance(target, JarLibrary):
      return False
    elif isinstance(target, (Dependencies, Resources)) or type(target) == Target:
      # ignore aliases and resources
      return False
    else:
      return True

  def _normalize_product_dep(self, buildroot, classes_by_source, dep):
    """Normalizes the given product dep from the given dep into a set of classfiles.

    Product deps arrive as sources, jars, and classfiles: this method normalizes them to classfiles.

    TODO: This normalization should happen in the super class.
    """
    if dep.endswith(".jar"):
      # TODO: post sbt/zinc jar output patch, binary deps will be reported directly as classfiles
      return set()
    elif dep.endswith(".class"):
      return set([dep])
    else:
      # assume a source file and convert to classfiles
      rel_src = fast_relpath(dep, buildroot)
      return set(p for _, paths in classes_by_source[rel_src].rel_paths() for p in paths)

  def create_dep_usage_graph(self, targets, buildroot):
    """Creates a graph of concrete targets, with their sum of products and dependencies.

    Synthetic targets contribute products and dependencies to their concrete target.
    """

    # Initialize all Nodes.
    classes_by_source = self.context.products.get_data('classes_by_source')
    classes_by_target = self.context.products.get_data('classes_by_target')
    product_deps_by_src = self.context.products.get_data('product_deps_by_src')
    nodes = dict()
    for target in targets:
      if not self._select(target):
        continue
      # Create or extend a Node for the concrete version of this target.
      concrete_target = target.concrete_derived_from
      products_total = sum(len(paths) for _, paths in classes_by_target[target].rel_paths())
      node = nodes.get(concrete_target)
      if not node:
        node = nodes.setdefault(concrete_target, Node(concrete_target))
      node.add_derivation(target, products_total)

      # Record declared Edges.
      for dep_tgt in self._resolve_aliases(target):
        derived_from = dep_tgt.concrete_derived_from
        if self._select(derived_from):
          node.add_edge(Edge(is_declared=True, products_used=set()), derived_from)

      # Record the used products and undeclared Edges for this target. Note that some of
      # these may be self edges, which are considered later.
      target_product_deps_by_src = product_deps_by_src.get(target, dict())
      for src in target.sources_relative_to_buildroot():
        for product_dep in target_product_deps_by_src.get(os.path.join(buildroot, src), []):
          for dep_tgt in self.targets_by_file.get(product_dep, []):
            derived_from = dep_tgt.concrete_derived_from
            if not self._select(derived_from):
              continue
            is_declared = self._is_declared_dep(target, dep_tgt)
            normalized_deps = self._normalize_product_dep(buildroot, classes_by_source, product_dep)
            node.add_edge(Edge(is_declared=is_declared, products_used=normalized_deps), derived_from)

    # Prune any Nodes with 0 products.
    for concrete_target, node in nodes.items()[:]:
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

  def add_derivation(self, derived_target, derived_products):
    self.derivations.add(derived_target)
    self.products_total += derived_products

  def add_edge(self, edge, dest):
    self.dep_edges[dest] += edge


class Edge(object):
  """Record a set of used products, and a boolean indicating that a depedency edge was declared."""

  def __init__(self, is_declared=False, products_used=None):
    self.products_used = products_used or set()
    self.is_declared = is_declared

  def __iadd__(self, that):
    self.products_used |= that.products_used
    self.is_declared |= that.is_declared
    return self


class DependencyUsageGraph(object):

  def __init__(self, nodes, size_estimator):
    self._nodes = nodes
    self._size_estimator = size_estimator
    self._cost_cache = {}
    self._trans_cost_cache = {}

  def _cost(self, target):
    if target not in self._cost_cache:
      self._cost_cache[target] = self._size_estimator(target.sources_relative_to_buildroot())
    return self._cost_cache[target]

  def _trans_cost(self, target):
    if target not in self._trans_cost_cache:
      dep_sum = sum(self._trans_cost(dep) for dep in target.dependencies)
      self._trans_cost_cache[target] = self._cost(target) + dep_sum
    return self._trans_cost_cache[target]

  def _edge_type(self, target, edge, dep):
    if target == dep:
      return 'self'
    elif edge.is_declared:
      return 'declared'
    else:
      return 'undeclared'

  def _used_ratio(self, dep_tgt, edge):
    dep_tgt_products_total = max(self._nodes[dep_tgt].products_total if dep_tgt in self._nodes else 1, 1)
    return len(edge.products_used) / dep_tgt_products_total

  def to_summary(self):
    """Outputs summarized dependencies ordered by a combination of max usage and cost."""

    # Aggregate inbound edges by their maximum product usage ratio.
    max_target_usage = defaultdict(lambda: 0.0)
    for target, node in self._nodes.items():
      for dep_target, edge in node.dep_edges.items():
        if target == dep_target:
          continue
        used_ratio = self._used_ratio(dep_target, edge)
        max_target_usage[dep_target] = max(max_target_usage[dep_target], used_ratio)

    # Calculate a score for each.
    Score = namedtuple('Score', ('badness', 'max_usage', 'cost_transitive', 'target'))
    scores = []
    for target, max_usage in max_target_usage.items():
      cost_transitive = self._trans_cost(target)
      score = int(cost_transitive / (max_usage if max_usage > 0.0 else 1.0))
      scores.append(Score(score, max_usage, cost_transitive, target.address.spec))

    # Output in order by score.
    yield '[\n'
    first = True
    for score in sorted(scores, key=lambda s: s.badness):
      yield '{}  {}'.format('' if first else ',\n', json.dumps(score._asdict()))
      first = False
    yield '\n]\n'

  def to_json(self):
    """Outputs the entire graph."""
    res_dict = {}
    def gen_dep_edge(node, edge, dep_tgt):
      return {
        'target': dep_tgt.address.spec,
        'dependency_type': self._edge_type(node.concrete_target, edge, dep_tgt),
        'products_used': len(edge.products_used),
        'products_used_ratio': self._used_ratio(dep_tgt, edge),
      }
    for node in self._nodes.values():
      res_dict[node.concrete_target.address.spec] = {
          'cost': self._cost(node.concrete_target),
          'cost_transitive': self._trans_cost(node.concrete_target),
          'products_total': node.products_total,
          'dependencies': [gen_dep_edge(node, edge, dep_tgt) for dep_tgt, edge in node.dep_edges.items()]
        }
    yield json.dumps(res_dict, indent=2, sort_keys=True)
