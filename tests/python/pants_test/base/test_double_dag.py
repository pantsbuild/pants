# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.base.double_dag import DoubleDag
from pants.reporting.report import Report
from pants_test.base_test import BaseTest
from pants_test.testutils.mock_logger import MockLogger


def make_dag(nodes):
  return DoubleDag(nodes, lambda t: t.dependencies, MockLogger(Report.INFO))


class DoubleDagTest(BaseTest):

  def check_dag_node(self, dag, data, children, parents):
    node = dag.lookup(data)

    self.assertEquals(node.data, data)
    self.assertEquals(node.children, set(map(dag.lookup, children)))
    self.assertEquals(node.parents, set(map(dag.lookup, parents)))

  def test_simple_dag(self):
    a = self.make_target('a')
    b = self.make_target('b', dependencies=[a])
    c = self.make_target('c', dependencies=[b])
    d = self.make_target('d', dependencies=[c, a])
    e = self.make_target('e', dependencies=[d])

    def test_dag(dag):
      self.assertEquals(dag._roots, set([dag.lookup(e)]))
      self.assertEquals(dag.leaves, set([dag.lookup(a)]))

      self.check_dag_node(dag, e, [d], [])
      self.check_dag_node(dag, d, [a, c], [e])
      self.check_dag_node(dag, c, [b], [d])
      self.check_dag_node(dag, b, [a], [c])
      self.check_dag_node(dag, a, [], [b, d])

    test_dag(make_dag([e, d, c, b, a]))
    test_dag(make_dag([a, b, c, d, e]))
    test_dag(make_dag([a, b, e, d, c]))
    test_dag(make_dag([d, a, c, e, b]))

  def test_binary_search_dag(self):

    rrr = self.make_target('rrr')
    rrl = self.make_target('rrl')
    rlr = self.make_target('rlr')
    rll = self.make_target('rll')
    lrr = self.make_target('lrr')
    lrl = self.make_target('lrl')
    llr = self.make_target('llr')
    lll = self.make_target('lll')

    rr = self.make_target('rr', dependencies=[rrr, rrl])
    rl = self.make_target('rl', dependencies=[rlr, rll])
    lr = self.make_target('lr', dependencies=[lrr, lrl])
    ll = self.make_target('ll', dependencies=[llr, lll])

    r = self.make_target('r', dependencies=[rr, rl])
    l = self.make_target('l', dependencies=[lr, ll])

    root = self.make_target('root', dependencies=[r, l])

    def test_dag(dag):

      def t(n):
        return dag.lookup(n)

      self.assertEquals(dag._roots, set([t(root)]))
      self.assertEquals(dag.leaves, set(map(t, [rrr, rrl, rlr, rll, lrr, lrl, llr, lll])))

      self.check_dag_node(dag, root, [r, l], [])

      self.check_dag_node(dag, r, [rl, rr], [root])
      self.check_dag_node(dag, l, [ll, lr], [root])

      self.check_dag_node(dag, rr, [rrl, rrr], [r])
      self.check_dag_node(dag, rl, [rll, rlr], [r])
      self.check_dag_node(dag, lr, [lrl, lrr], [l])
      self.check_dag_node(dag, ll, [lll, llr], [l])

      self.check_dag_node(dag, rrr, [], [rr])
      self.check_dag_node(dag, rrl, [], [rr])
      self.check_dag_node(dag, rlr, [], [rl])
      self.check_dag_node(dag, rll, [], [rl])
      self.check_dag_node(dag, lrr, [], [lr])
      self.check_dag_node(dag, lrl, [], [lr])
      self.check_dag_node(dag, llr, [], [ll])
      self.check_dag_node(dag, lll, [], [ll])

    # Test in order
    test_dag(make_dag([root, r, l, rr, rl, lr, ll, rrr, rrl, rlr, rll, lrr, lrl, llr, lll]))

    # Test a couple of randomly chosen orders
    test_dag(make_dag([lrl, r, root, rl, rrr, rll, lr, lrr, ll, lll, l, rr, rrl, rlr, llr]))
    test_dag(make_dag([ll, rrl, lrl, rl, rlr, lr, root, rrr, rll, r, llr, rr, lrr, l, lll]))
    test_dag(make_dag([rr, rlr, rl, rrr, rrl, l, root, lr, lrr, llr, r, rll, lrl, ll, lll]))
    test_dag(make_dag([l, lll, rrr, rll, ll, lrl, llr, rl, root, r, lr, rlr, rr, lrr, rrl]))

  def test_diamond_in_different_orders(self):
    a = self.make_target('a')
    b = self.make_target('b', dependencies=[a])
    c = self.make_target('c', dependencies=[a])
    d = self.make_target('d', dependencies=[c, b])

    def test_diamond_dag(dag):
      self.assertEquals(dag._roots, set([dag.lookup(d)]))
      self.assertEquals(dag.leaves, set([dag.lookup(a)]))
      self.check_dag_node(dag, d, [b, c], [])
      self.check_dag_node(dag, c, [a], [d])
      self.check_dag_node(dag, b, [a], [d])
      self.check_dag_node(dag, a, [], [b, c])

    test_diamond_dag(make_dag([a, b, c, d]))
    test_diamond_dag(make_dag([d, c, b, a]))
    test_diamond_dag(make_dag([b, d, a, c]))

  def test_find_children_across_unused_target(self):
    a = self.make_target('a')
    b = self.make_target('b', dependencies=[a])
    c = self.make_target('c', dependencies=[b])
    d = self.make_target('d', dependencies=[c, a])
    e = self.make_target('e', dependencies=[d])
