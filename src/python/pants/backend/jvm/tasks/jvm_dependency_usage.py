# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import json
import os
import sys
from collections import defaultdict, namedtuple

from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.tasks.jvm_dependency_analyzer import JvmDependencyAnalyzer
from pants.base.build_environment import get_buildroot
from pants.build_graph.aliased_target import AliasTarget
from pants.build_graph.resources import Resources
from pants.build_graph.target import Target
from pants.build_graph.target_scopes import Scopes
from pants.task.task import Task
from pants.util.fileutil import create_size_estimators


class JvmDependencyUsage(Task):
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
    register('--internal-only', default=False, type=bool, fingerprint=True,
             help='Specifies that only internal dependencies should be included in the graph '
                  'output (no external jars).')
    register('--summary', default=True, type=bool,
             help='When set, outputs a summary of the "worst" dependencies; otherwise, '
                  'outputs a JSON report.')
    register('--size-estimator',
             choices=list(cls.size_estimators.keys()), default='filesize', fingerprint=True,
             help='The method of target size estimation.')
    register('--transitive', default=True, type=bool,
             help='Score all targets in the build graph transitively.')
    register('--output-file', type=str,
             help='Output destination. When unset, outputs to <stdout>.')
    register('--use-cached', type=bool,
             help='Use cached dependency data to compute analysis result. '
                  'When set, skips `resolve` and `compile` steps. '
                  'Useful for computing analysis for a lot of targets, but '
                  'result can differ from direct execution because cached information '
                  'doesn\'t depend on 3rdparty libraries versions.')

  @classmethod
  def prepare(cls, options, round_manager):
    super(JvmDependencyUsage, cls).prepare(options, round_manager)
    if not options.use_cached:
      round_manager.require_data('classes_by_source')
      round_manager.require_data('runtime_classpath')
      round_manager.require_data('product_deps_by_src')
    else:
      # We want to have synthetic targets in build graph to deserialize nodes properly.
      round_manager.require_data('java')
      round_manager.require_data('scala')
      round_manager.require_data('deferred_sources')

  @classmethod
  def skip(cls, options):
    """This task is always explicitly requested."""
    return False

  def execute(self):
    graph = self.create_dep_usage_graph(self.context.targets() if self.get_options().transitive
                                        else self.context.target_roots)
    output_file = self.get_options().output_file
    if output_file:
      self.context.log.info('Writing dependency usage to {}'.format(output_file))
      with open(output_file, 'w') as fh:
        self._render(graph, fh)
    else:
      sys.stdout.write(b'\n')
      self._render(graph, sys.stdout)

  @classmethod
  def implementation_version(cls):
    return super(JvmDependencyUsage, cls).implementation_version() + [('JvmDependencyUsage', 7)]

  def _render(self, graph, fh):
    chunks = graph.to_summary() if self.get_options().summary else graph.to_json()
    for chunk in chunks:
      fh.write(chunk)
    fh.flush()

  def _dep_type(self, target, dep, declared_deps, eligible_unused_deps, is_used):
    """Returns a tuple of a 'declared'/'undeclared' boolean, and 'used'/'unused' boolean.

    These values are related, because some declared deps are not eligible to be considered unused.

    :param target: The source target.
    :param dep: The dependency to compute a type for.
    :param declared_deps: The declared dependencies of the target.
    :param eligible_unused_deps: The declared dependencies of the target that are eligible
      to be considered unused; this is generally only 'DEFAULT' scoped dependencies.
    :param is_used: True if the dep was actually used at compile time.
    """
    if target == dep:
      return True, True
    return (dep in declared_deps), (is_used or dep not in eligible_unused_deps)

  def _select(self, target):
    if self.get_options().internal_only and isinstance(target, JarLibrary):
      return False
    elif isinstance(target, Resources) or type(target) in (AliasTarget, Target):
      return False
    else:
      return True

  def create_dep_usage_graph(self, targets):
    """Creates a graph of concrete targets, with their sum of products and dependencies.

    Synthetic targets contribute products and dependencies to their concrete target.
    """
    with self.invalidated(targets,
                          invalidate_dependents=True) as invalidation_check:
      target_to_vts = {}
      for vts in invalidation_check.all_vts:
        target_to_vts[vts.target] = vts

      if not self.get_options().use_cached:
        node_creator = self.calculating_node_creator(
          self.context.products.get_data('classes_by_source'),
          self.context.products.get_data('runtime_classpath'),
          self.context.products.get_data('product_deps_by_src'),
          target_to_vts)
      else:
        node_creator = self.cached_node_creator(target_to_vts)

      return DependencyUsageGraph(self.create_dep_usage_nodes(targets, node_creator),
                                  self.size_estimators[self.get_options().size_estimator])

  def calculating_node_creator(self, classes_by_source, runtime_classpath, product_deps_by_src,
                               target_to_vts):
    """Strategy directly computes dependency graph node based on
    `classes_by_source`, `runtime_classpath`, `product_deps_by_src` parameters and
    stores the result to the build cache.
    """
    analyzer = JvmDependencyAnalyzer(get_buildroot(), runtime_classpath, product_deps_by_src)
    targets = self.context.targets()
    targets_by_file = analyzer.targets_by_file(targets)
    transitive_deps_by_target = analyzer.compute_transitive_deps_by_target(targets)
    def creator(target):
      transitive_deps = set(transitive_deps_by_target.get(target))
      node = self.create_dep_usage_node(target,
                                        analyzer,
                                        classes_by_source,
                                        targets_by_file,
                                        transitive_deps)
      vt = target_to_vts[target]
      with open(self.nodes_json(vt.results_dir), mode='w') as fp:
        json.dump(node.to_cacheable_dict(), fp, indent=2, sort_keys=True)
      vt.update()
      return node

    return creator

  def cached_node_creator(self, target_to_vts):
    """Strategy restores dependency graph node from the build cache.
    """
    def creator(target):
      vt = target_to_vts[target]
      if vt.valid and os.path.exists(self.nodes_json(vt.results_dir)):
        try:
          with open(self.nodes_json(vt.results_dir)) as fp:
            return Node.from_cacheable_dict(json.load(fp),
                                            lambda spec: self.context.resolve(spec).__iter__().next())
        except Exception:
          self.context.log.warn("Can't deserialize json for target {}".format(target))
          return Node(target.concrete_derived_from)
      else:
        self.context.log.warn("No cache entry for {}".format(target))
        return Node(target.concrete_derived_from)

    return creator

  def nodes_json(self, target_results_dir):
    return os.path.join(target_results_dir, 'node.json')

  def create_dep_usage_nodes(self, targets, node_creator):
    nodes = {}
    for target in targets:
      if not self._select(target):
        continue
      # Create or extend a Node for the concrete version of this target.
      concrete_target = target.concrete_derived_from
      node = node_creator(target)
      if concrete_target in nodes:
        nodes[concrete_target].combine(node)
      else:
        nodes[concrete_target] = node

    # Prune any Nodes with 0 products.
    for concrete_target, node in nodes.items()[:]:
      if node.products_total == 0:
        nodes.pop(concrete_target)

    return nodes

  def cache_target_dirs(self):
    return True

  def create_dep_usage_node(self, target, analyzer, classes_by_source, targets_by_file, transitive_deps):
    buildroot = analyzer.buildroot
    product_deps_by_src = analyzer.product_deps_by_src
    declared_deps_with_aliases = set(analyzer.resolve_aliases(target))
    eligible_unused_deps = set(d for d, _ in analyzer.resolve_aliases(target, scope=Scopes.DEFAULT))
    concrete_target = target.concrete_derived_from
    declared_deps = [resolved for resolved, _ in declared_deps_with_aliases]
    products_total = analyzer.count_products(target)
    node = Node(concrete_target)
    node.add_derivation(target, products_total)

    def _construct_edge(dep_tgt, products_used):
      is_declared, is_used = self._dep_type(target,
                                            dep_tgt,
                                            declared_deps,
                                            eligible_unused_deps,
                                            len(products_used) > 0)
      return Edge(is_declared=is_declared, is_used=is_used, products_used=products_used)

    # Record declared Edges, initially all as "unused" or "declared".
    for dep_tgt, aliased_from in declared_deps_with_aliases:
      derived_from = dep_tgt.concrete_derived_from
      if self._select(derived_from):
        node.add_edge(_construct_edge(dep_tgt, products_used=set()), derived_from, aliased_from)

    # Record the used products and undeclared Edges for this target. Note that some of
    # these may be self edges, which are considered later.
    target_product_deps_by_src = product_deps_by_src.get(target, {})
    for src in target.sources_relative_to_buildroot():
      for product_dep in target_product_deps_by_src.get(os.path.join(buildroot, src), []):
        for dep_tgt in targets_by_file.get(product_dep, []):
          derived_from = dep_tgt.concrete_derived_from
          if not self._select(derived_from):
            continue
          # Create edge only for those direct or transitive dependencies in order to
          # disqualify irrelevant targets that happen to share some file in sources,
          # not uncommon when globs especially rglobs is used.
          if not derived_from in transitive_deps:
            continue
          node.add_edge(_construct_edge(dep_tgt, products_used={product_dep}), derived_from)

    return node


class Node(object):
  def __init__(self, concrete_target):
    self.concrete_target = concrete_target
    self.products_total = 0
    self.derivations = set()
    # Dict mapping concrete dependency targets to an Edge object.
    self.dep_edges = defaultdict(Edge)
    # Dict mapping concrete dependency targets to where they are aliased from.
    self.dep_aliases = defaultdict(set)

  def add_derivation(self, derived_target, derived_products):
    self.derivations.add(derived_target)
    self.products_total += derived_products

  def add_edge(self, edge, dest, dest_aliased_from=None):
    self.dep_edges[dest] += edge
    if dest_aliased_from:
      self.dep_aliases[dest].add(dest_aliased_from)

  def combine(self, other_node):
    assert other_node.concrete_target == self.concrete_target
    self.products_total += other_node.products_total
    self.derivations.update(other_node.derivations)
    self.dep_edges.update(other_node.dep_edges)
    self.dep_aliases.update(other_node.dep_aliases)

  def to_cacheable_dict(self):
    edges = {}
    for dest in self.dep_edges:
      edges[dest.address.spec] = {
        'products_used': list(self.dep_edges[dest].products_used),
        'is_declared': self.dep_edges[dest].is_declared,
        'is_used': self.dep_edges[dest].is_used,
      }
    aliases = {}

    for dep, dep_aliases in self.dep_aliases.items():
      aliases[dep.address.spec] = [alias.address.spec for alias in dep_aliases]

    return {
      'target': self.concrete_target.address.spec,
      'products_total': self.products_total,
      'derivations': [derivation.address.spec for derivation in self.derivations],
      'dep_edges': edges,
      'aliases': aliases,
    }

  @staticmethod
  def from_cacheable_dict(cached_dict, target_resolve_func):
    res = Node(target_resolve_func(cached_dict['target']))
    res.products_total = cached_dict['products_total']
    res.derivations.update([target_resolve_func(spec) for spec in cached_dict['derivations']])
    for edge in cached_dict['dep_edges']:
      res.dep_edges[target_resolve_func(edge)] = Edge(
        is_declared=cached_dict['dep_edges'][edge]['is_declared'],
        is_used=cached_dict['dep_edges'][edge]['is_used'],
        products_used=set(cached_dict['dep_edges'][edge]['products_used']))
    for dep in cached_dict['aliases']:
      for alias in cached_dict['aliases'][dep]:
        res.dep_aliases[target_resolve_func(dep)].add(target_resolve_func(alias))
    return res


class Edge(object):
  """Record a set of used products, and a boolean indicating that a depedency edge was declared."""

  def __init__(self, is_declared=False, is_used=False, products_used=None):
    self.products_used = products_used or set()
    self.is_declared = is_declared
    self.is_used = is_used

  def __iadd__(self, that):
    self.products_used |= that.products_used
    self.is_declared |= that.is_declared
    self.is_used |= that.is_used
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
    elif edge.is_declared and edge.is_used:
      return 'declared'
    elif edge.is_declared and not edge.is_used:
      return 'unused'
    else:
      return 'undeclared'

  def _used_ratio(self, dep_tgt, edge):
    if edge.products_used:
      # If products were recorded as used, generate a legitimate ratio.
      dep_tgt_products_total = self._nodes[dep_tgt].products_total if dep_tgt in self._nodes else 1
      return len(edge.products_used) / max(dep_tgt_products_total, 1)
    elif edge.is_used:
      # Else, the dep might not be in the default scope, and must considered to be used.
      return 1.0
    else:
      # Otherwise, definitely not used.
      return 0.0

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

    def gen_dep_edge(node, edge, dep_tgt, aliases):
      return {
        'target': dep_tgt.address.spec,
        'dependency_type': self._edge_type(node.concrete_target, edge, dep_tgt),
        'products_used': len(edge.products_used),
        'products_used_ratio': self._used_ratio(dep_tgt, edge),
        'aliases': [alias.address.spec for alias in aliases],
      }

    for node in self._nodes.values():
      res_dict[node.concrete_target.address.spec] = {
        'cost': self._cost(node.concrete_target),
        'cost_transitive': self._trans_cost(node.concrete_target),
        'products_total': node.products_total,
        'dependencies': [gen_dep_edge(node, edge, dep_tgt, node.dep_aliases.get(dep_tgt, {}))
                         for dep_tgt, edge in node.dep_edges.items()],
      }
    yield json.dumps(res_dict, indent=2, sort_keys=True)
