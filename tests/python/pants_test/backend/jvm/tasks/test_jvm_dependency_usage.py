# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.tasks.classpath_products import ClasspathProducts
from pants.backend.jvm.tasks.jvm_dependency_analyzer import JvmDependencyAnalyzer
from pants.backend.jvm.tasks.jvm_dependency_usage import DependencyUsageGraph, JvmDependencyUsage
from pants.util.dirutil import safe_mkdir, touch
from pants_test.tasks.task_test_base import TaskTestBase, ensure_cached


class TestJvmDependencyUsage(TaskTestBase):

  @classmethod
  def task_type(cls):
    return JvmDependencyUsage

  def _setup(self, target_classfiles):
    """Takes a dict mapping targets to lists of classfiles."""
    context = self.context(target_roots=target_classfiles.keys())

    # Create classfiles in a target-specific directory, and add it to the classpath for the target.
    classpath_products = context.products.get_data('runtime_classpath', ClasspathProducts.init_func(self.pants_workdir))
    for target, classfiles in target_classfiles.items():
      target_dir = os.path.join(self.test_workdir, target.id)
      safe_mkdir(target_dir)
      for classfile in classfiles:
        touch(os.path.join(target_dir, classfile))
      classpath_products.add_for_target(target, [('default', target_dir)])

    product_deps_by_src = context.products.get_data('product_deps_by_src', dict)
    return self.create_task(context), product_deps_by_src

  def make_java_target(self, *args, **kwargs):
    assert 'target_type' not in kwargs
    return self.make_target(target_type=JavaLibrary, *args, **kwargs)

  def _cover_output(self, graph):
    # coverage of the output code
    self.assertNotEqual(graph.to_json(), "")
    self.assertNotEqual(graph.to_summary(), "")

  def test_simple_dep_usage_graph(self):
    t1 = self.make_java_target(spec=':t1', sources=['a.java', 'b.java'])
    t2 = self.make_java_target(spec=':t2', sources=['c.java'], dependencies=[t1])
    t3 = self.make_java_target(spec=':t3', sources=['d.java', 'e.java'], dependencies=[t1])
    self.set_options(size_estimator='filecount')
    dep_usage, product_deps_by_src = self._setup({
        t1: ['a.class', 'b.class'],
        t2: ['c.class'],
        t3: ['d.class', 'e.class'],
      })
    product_deps_by_src[t1] = {}
    product_deps_by_src[t2] = {'c.java': ['a.class']}
    product_deps_by_src[t3] = {'d.java': ['a.class', 'b.class'],
                               'e.java': ['a.class', 'b.class']}

    graph = self.create_graph(dep_usage, [t1, t2, t3])

    self.assertEqual(graph._nodes[t1].products_total, 2)
    self.assertEqual(graph._nodes[t2].products_total, 1)
    self.assertEqual(graph._nodes[t3].products_total, 2)

    self.assertEqual(graph._nodes[t1].dep_edges, {})
    self.assertEqual(len(graph._nodes[t2].dep_edges[t1].products_used), 1)
    self.assertEqual(len(graph._nodes[t3].dep_edges[t1].products_used), 2)

    self.assertEqual(graph._trans_cost(t1), 2)
    self.assertEqual(graph._trans_cost(t2), 3)
    self.assertEqual(graph._trans_cost(t3), 4)

    self._cover_output(graph)

  def test_dep_usage_graph_with_synthetic_targets(self):
    t1 = self.make_java_target(spec=':t1', sources=['t1.thrift'])
    t1_x = self.make_java_target(spec=':t1.x', derived_from=t1)
    t1_y = self.make_java_target(spec=':t1.y', derived_from=t1)
    t1_z = self.make_java_target(spec=':t1.z', derived_from=t1)
    t2 = self.make_java_target(spec=':t2',
                               sources=['a.java', 'b.java'],
                               dependencies=[t1, t1_x, t1_y, t1_z])
    self.set_options(size_estimator='nosize')
    dep_usage, product_deps_by_src = self._setup({
        t1_x: ['x1.class'],
        t1_y: ['y1.class'],
        t1_z: ['z1.class', 'z2.class', 'z3.class'],
        t2: ['a.class', 'b.class'],
      })
    product_deps_by_src[t1] = {}
    product_deps_by_src[t1_x] = {}
    product_deps_by_src[t1_y] = {}
    product_deps_by_src[t1_z] = {}
    product_deps_by_src[t2] = {'a.java': ['x1.class'],
                               'b.java': ['z1.class', 'z2.class']}
    graph = self.create_graph(dep_usage, [t1, t1_x, t1_y, t1_z, t2])

    self.assertEqual(graph._nodes[t1].products_total, 5)
    self.assertEqual(len(graph._nodes[t2].dep_edges[t1].products_used), 3)

    self._cover_output(graph)

  def test_target_alias(self):
    a = self.make_java_target(spec=':a', sources=['a.java'])
    b = self.make_java_target(spec=':b', sources=['b.java'])
    alias_a_b = self.make_target(spec=':alias_a_b', dependencies=[a, b])
    alias_b = self.make_target(spec=':alias_b', dependencies=[b])
    nested_alias_b = self.make_target(spec=':nest_alias_b', dependencies=[alias_b])
    c = self.make_java_target(spec=':c', sources=['c.java'], dependencies=[alias_a_b, nested_alias_b])
    self.set_options(strict_deps=False)
    dep_usage, product_deps_by_src = self._setup({
      a: ['a.class'],
      b: ['b.class'],
      c: ['c.class'],
    })

    product_deps_by_src[c] = {'c.java': ['a.class']}
    graph = self.create_graph(dep_usage, [a, b, c, alias_a_b, alias_b, nested_alias_b])
    # both `:a` and `:b` are resolved from target aliases, one is used the other is not.
    self.assertTrue(graph._nodes[c].dep_edges[a].is_declared)
    self.assertEquals({'a.class'}, graph._nodes[c].dep_edges[a].products_used)
    self.assertTrue(graph._nodes[c].dep_edges[b].is_declared)
    self.assertEquals(set(), graph._nodes[c].dep_edges[b].products_used)

    # With alias to its resolved targets mapping we can determine which aliases are unused.
    # In this example `nested_alias_b` has none of its resolved dependencies being used.
    # Also note when there are transitive aliases only top level alias `nested_alias_b` is saved.
    self.assertEqual({alias_a_b}, graph._nodes[c].dep_aliases[a])
    self.assertEqual({nested_alias_b, alias_a_b}, graph._nodes[c].dep_aliases[b])

  def test_overlapping_globs(self):
    t1 = self.make_java_target(spec=':t1', sources=['a.java'])
    t2 = self.make_java_target(spec=':t2', sources=['a.java', 'b.java'])
    t3 = self.make_java_target(spec=':t3', sources=['c.java'], dependencies=[t1])
    t4 = self.make_java_target(spec=':t4', sources=['d.java'], dependencies=[t3])
    self.set_options(strict_deps=False)
    dep_usage, product_deps_by_src = self._setup({
        t1: ['a.class'],
        t2: ['a.class', 'b.class'],
        t3: ['c.class'],
        t4: ['d.class'],
    })
    product_deps_by_src[t3] = {'c.java': ['a.class']}
    product_deps_by_src[t4] = {'d.java': ['a.class']}
    graph = self.create_graph(dep_usage, [t1, t2, t3, t4])

    # Not creating edge for t2 even it provides a.class that t4 depends on.
    self.assertFalse(t2 in graph._nodes[t4].dep_edges)
    # t4 depends on a.class from t1 transitively through t3.
    self.assertEqual({'a.class'}, graph._nodes[t4].dep_edges[t1].products_used)
    self.assertFalse(graph._nodes[t4].dep_edges[t1].is_declared)
    self.assertEqual(set(), graph._nodes[t4].dep_edges[t3].products_used)
    self.assertTrue(graph._nodes[t4].dep_edges[t3].is_declared)

  def create_graph(self, task, targets):
    classes_by_source = task.context.products.get_data('classes_by_source')
    runtime_classpath = task.context.products.get_data('runtime_classpath')
    product_deps_by_src = task.context.products.get_data('product_deps_by_src')
    analyzer = JvmDependencyAnalyzer('', runtime_classpath, product_deps_by_src)
    targets_by_file = analyzer.targets_by_file(targets)
    transitive_deps_by_target = analyzer.compute_transitive_deps_by_target(targets)

    def node_creator(target):
      transitive_deps = set(transitive_deps_by_target.get(target))
      return task.create_dep_usage_node(target,
                                        analyzer,
                                        classes_by_source,
                                        targets_by_file,
                                        transitive_deps)

    return DependencyUsageGraph(task.create_dep_usage_nodes(targets, node_creator),
                                task.size_estimators[task.get_options().size_estimator])

  @ensure_cached(JvmDependencyUsage, expected_num_artifacts=2)
  def test_cache_write(self):
    t1 = self.make_java_target(spec=':t1', sources=['a.java'])
    self.create_file('a.java')
    t2 = self.make_java_target(spec=':t2', sources=['b.java'], dependencies=[t1])
    self.create_file('b.java')
    self.set_options(size_estimator='filecount')
    dep_usage, product_deps_by_src = self._setup({
        t1: ['a.class'],
        t2: ['b.class'],
      })
    product_deps_by_src[t1] = {}
    product_deps_by_src[t2] = {'b.java': ['a.class']}

    dep_usage.create_dep_usage_graph([t1, t2])
