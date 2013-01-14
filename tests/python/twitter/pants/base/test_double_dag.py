__author__ = 'Ryan Williams'

import unittest

from twitter.pants.base import DoubleDag
from twitter.pants.goal import Context
from twitter.pants.testutils import MockTarget

def make_dag(nodes):
  return DoubleDag(nodes, lambda t: t.dependencies, Context.Log())

class DoubleDagTest(unittest.TestCase):

  def check_dag_node(self, dag, data, children, parents):
    node = dag.lookup(data)

    self.assertEquals(node.data, data)
    self.assertEquals(node.children, set(map(dag.lookup, children)))
    self.assertEquals(node.parents, set(map(dag.lookup, parents)))

  def test_simple_dag(self):
    a = MockTarget('a')
    b = MockTarget('b', [a])
    c = MockTarget('c', [b])
    d = MockTarget('d', [c, a])
    e = MockTarget('e', [d])

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

    rrr = MockTarget('rrr')
    rrl = MockTarget('rrl')
    rlr = MockTarget('rlr')
    rll = MockTarget('rll')
    lrr = MockTarget('lrr')
    lrl = MockTarget('lrl')
    llr = MockTarget('llr')
    lll = MockTarget('lll')

    rr = MockTarget('rr', [rrr, rrl])
    rl = MockTarget('rl', [rlr, rll])
    lr = MockTarget('lr', [lrr, lrl])
    ll = MockTarget('ll', [llr, lll])

    r = MockTarget('r', [rr, rl])
    l = MockTarget('l', [lr, ll])

    root = MockTarget('root', [r, l])

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
    a = MockTarget('a')
    b = MockTarget('b', [a])
    c = MockTarget('c', [a])
    d = MockTarget('d', [c, b])

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
    a = MockTarget('a')
    b = MockTarget('b', [a])
    c = MockTarget('c', [b])
    d = MockTarget('d', [c, a])
    e = MockTarget('e', [d])

