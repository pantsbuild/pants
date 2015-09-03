# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from collections import defaultdict

from pants.backend.jvm.tasks.jvm_dependency_usage import JvmDependencyUsage
from pants.base.payload import Payload
from pants.base.payload_field import SourcesField
from pants.goal.products import MultipleRootedProducts
from pants_test.tasks.task_test_base import TaskTestBase


class TestJvmDependencyUsage(TaskTestBase):

  @classmethod
  def task_type(cls):
    return JvmDependencyUsage

  def _make_payload_from_sources(self, sources):
    p = Payload()
    p.add_field('sources', SourcesField('', sources))
    p.freeze()
    return p

  def _setup_products(self, context):
    classes_by_target = context.products.get_data('classes_by_target',
                                                  lambda: defaultdict(MultipleRootedProducts))
    product_deps_by_src = context.products.get_data('product_deps_by_src', dict)
    return classes_by_target, product_deps_by_src

  def test_simple_dep_usage_graph(self):
    t1 = self.make_target(spec=':t1',
                          payload=self._make_payload_from_sources(['a.java', 'b.java']))
    t2 = self.make_target(spec=':t2',
                          payload=self._make_payload_from_sources(['c.java']),
                          dependencies=[t1])
    t3 = self.make_target(spec=':t3',
                          payload=self._make_payload_from_sources(['d.java', 'e.java']),
                          dependencies=[t1])
    self.set_options(size_estimator='filecount')
    context = self.context()
    classes_by_target, product_deps_by_src = self._setup_products(context)
    classes_by_target[t1].add_rel_paths('', ['a.class', 'b.class'])
    classes_by_target[t2].add_rel_paths('', ['c.class'])
    classes_by_target[t3].add_rel_paths('', ['d.class', 'e.class'])
    product_deps_by_src[t1] = {}
    product_deps_by_src[t2] = {'c.java': ['a.class']}
    product_deps_by_src[t3] = {'d.java': ['a.class', 'b.class'],
                               'e.java': ['a.class', 'b.class']}

    dep_usage = self.create_task(context)
    graph = dep_usage.create_dep_usage_graph([t1, t2, t3], '')

    self.assertEqual(graph[t1].usage_by_dep, {})
    self.assertEqual(graph[t2].usage_by_dep[graph[t1]], (1, 2))
    self.assertEqual(graph[t3].usage_by_dep[graph[t1]], (2, 2))

    usage_stats_by_node = graph._aggregate_product_usage_stats()
    self.assertEqual(usage_stats_by_node[graph[t1]], (1, 2, 3))
    self.assertEqual(usage_stats_by_node[graph[t2]], (0, 0, 0))
    self.assertEqual(usage_stats_by_node[graph[t3]], (0, 0, 0))

    self.assertEqual(graph._trans_job_size(t1), 2)
    self.assertEqual(graph._trans_job_size(t2), 3)
    self.assertEqual(graph._trans_job_size(t3), 4)

  def test_dep_usage_graph_with_synthetic_targets(self):
    t1 = self.make_target(spec=':t1', payload=self._make_payload_from_sources(['t1.thrift']))
    t1_x = self.make_target(spec=':t1.x', derived_from=t1)
    t1_y = self.make_target(spec=':t1.y', derived_from=t1)
    t1_z = self.make_target(spec=':t1.z', derived_from=t1)
    t2 = self.make_target(spec=':t2',
                          payload=self._make_payload_from_sources(['a.java', 'b.java']),
                          dependencies=[t1, t1_x, t1_y, t1_z])
    self.set_options(size_estimator='nosize')
    context = self.context()
    classes_by_target, product_deps_by_src = self._setup_products(context)
    classes_by_target[t1_x].add_rel_paths('', ['x1.class'])
    classes_by_target[t1_y].add_rel_paths('', ['y1.class'])
    classes_by_target[t1_z].add_rel_paths('', ['z1.class', 'z2.class', 'z3.class'])
    product_deps_by_src[t1] = {}
    product_deps_by_src[t1_x] = {}
    product_deps_by_src[t1_y] = {}
    product_deps_by_src[t1_z] = {}
    product_deps_by_src[t2] = {'a.java': ['x1.class'],
                               'b.java': ['z1.class', 'z2.class']}
    dep_usage = self.create_task(context)
    graph = dep_usage.create_dep_usage_graph([t1, t1_x, t1_y, t1_z, t2], '')

    self.assertEqual(graph[t2].usage_by_dep[graph[t1]], (3, 5))
