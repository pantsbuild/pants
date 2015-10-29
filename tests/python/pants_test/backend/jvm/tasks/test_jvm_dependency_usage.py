# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from collections import defaultdict

from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.tasks.classpath_products import ClasspathProducts
from pants.backend.jvm.tasks.jvm_dependency_usage import JvmDependencyUsage
from pants.goal.products import MultipleRootedProducts
from pants.util.dirutil import safe_mkdir, touch
from pants_test.tasks.task_test_base import TaskTestBase


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

    graph = dep_usage.create_dep_usage_graph([t1, t2, t3], '')

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
    graph = dep_usage.create_dep_usage_graph([t1, t1_x, t1_y, t1_z, t2], '')

    self.assertEqual(graph._nodes[t1].products_total, 5)
    self.assertEqual(len(graph._nodes[t2].dep_edges[t1].products_used), 3)

    self._cover_output(graph)
