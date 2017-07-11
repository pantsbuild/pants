# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import functools
import unittest

from pants.engine.nodes import Return


_WAITING = 'TODO: Waiting'


@unittest.skip('Skipped to expedite landing #3821; see: #4027.')
class GraphTest(unittest.TestCase):

  def setUp(self):
    super(GraphTest, self).setUp()
    self.pg = 'TODO: These tests need to be ported to native tests.'

  @classmethod
  def _mk_chain(cls, graph, sequence, states=[_WAITING, Return]):
    """Create a chain of dependencies (e.g. 'A'->'B'->'C'->'D') in the graph from a sequence."""
    for state in states:
      dest = None
      for src in reversed(sequence):
        if state is _WAITING:
          graph.add_dependencies(src, [dest] if dest else [])
        else:
          graph.complete_node(src, state([dest]))
        dest = src
    return sequence

  def test_disallow_completed_state_change(self):
    self.pg.complete_node('A', Return('done!'))
    with self.assertRaises('TODO: CompletedNodeException: These tests should be ported to native tests.'):
      self.pg.add_dependencies('A', ['B'])

  def test_disallow_completing_with_incomplete_deps(self):
    self.pg.add_dependencies('A', ['B'])
    self.pg.add_dependencies('B', ['C'])
    with self.assertRaises('TODO: IncompleteDependencyException: These tests should be ported to native tests.'):
      self.pg.complete_node('A', Return('done!'))

  def test_dependency_edges(self):
    self.pg.add_dependencies('A', ['B', 'C'])
    self.assertEquals({'B', 'C'}, set(self.pg.dependencies_of('A')))
    self.assertEquals({'A'}, set(self.pg.dependents_of('B')))
    self.assertEquals({'A'}, set(self.pg.dependents_of('C')))

  def test_cycle_simple(self):
    self.pg.add_dependencies('A', ['B'])
    self.pg.add_dependencies('B', ['A'])
    # NB: Order matters: the second insertion is the one tracked as a cycle.
    self.assertEquals({'B'}, set(self.pg.dependencies_of('A')))
    self.assertEquals(set(), set(self.pg.dependencies_of('B')))
    self.assertEquals(set(), set(self.pg.cyclic_dependencies_of('A')))
    self.assertEquals({'A'}, set(self.pg.cyclic_dependencies_of('B')))

  def test_cycle_indirect(self):
    self.pg.add_dependencies('A', ['B'])
    self.pg.add_dependencies('B', ['C'])
    self.pg.add_dependencies('C', ['A'])

    self.assertEquals({'B'}, set(self.pg.dependencies_of('A')))
    self.assertEquals({'C'}, set(self.pg.dependencies_of('B')))
    self.assertEquals(set(), set(self.pg.dependencies_of('C')))
    self.assertEquals(set(), set(self.pg.cyclic_dependencies_of('A')))
    self.assertEquals(set(), set(self.pg.cyclic_dependencies_of('B')))
    self.assertEquals({'A'}, set(self.pg.cyclic_dependencies_of('C')))

  def test_cycle_long(self):
    # Creating a long chain is allowed.
    nodes = list(range(0, 100))
    self._mk_chain(self.pg, nodes, states=(_WAITING,))
    walked_nodes = [node for node, _ in self.pg.walk([nodes[0]])]
    self.assertEquals(nodes, walked_nodes)

    # Closing the chain is not.
    begin, end = nodes[0], nodes[-1]
    self.pg.add_dependencies(end, [begin])
    self.assertEquals(set(), set(self.pg.dependencies_of(end)))
    self.assertEquals({begin}, set(self.pg.cyclic_dependencies_of(end)))

  def test_walk(self):
    nodes = list('ABCDEF')
    self._mk_chain(self.pg, nodes)
    walked_nodes = list((node for node, _ in self.pg.walk(nodes[0])))
    self.assertEquals(nodes, walked_nodes)

  def test_invalidate_all(self):
    chain_list = list('ABCDEFGHIJKLMNOPQRSTUVWXYZ')
    invalidators = (
      self.pg.invalidate,
      functools.partial(self.pg.invalidate, lambda node, _: node == 'Z')
    )

    for invalidator in invalidators:
      self._mk_chain(self.pg, chain_list)

      self.assertTrue(self.pg.completed_nodes())
      self.assertTrue(self.pg.dependents())
      self.assertTrue(self.pg.dependencies())
      self.assertTrue(self.pg.cyclic_dependencies())

      invalidator()

      self.assertFalse(self.pg._nodes)

  def test_invalidate_partial(self):
    comparison_pg = 'TODO: These tests need to be ported to native tests.'
    chain_a = list('ABCDEF')
    chain_b = list('GHIJKL')

    # Add two dependency chains to the primary graph.
    self._mk_chain(self.pg, chain_a)
    self._mk_chain(self.pg, chain_b)

    # Add only the dependency chain we won't invalidate to the comparison graph.
    self._mk_chain(comparison_pg, chain_b)

    # Invalidate one of the chains in the primary graph from the right-most node.
    self.pg.invalidate(lambda node, _: node == chain_a[-1])

    # Ensure the final structure of the primary graph matches the comparison graph.
    pg_structure = {n: e.structure() for n, e in self.pg._nodes.items()}
    comparison_structure = {n: e.structure() for n, e in comparison_pg._nodes.items()}
    self.assertEquals(pg_structure, comparison_structure)

  def test_invalidate_count(self):
    self._mk_chain(self.pg, list('ABCDEFGHIJKLMNOPQRSTUVWXYZ'))
    invalidated_count = self.pg.invalidate(lambda node, _: node == 'I')
    self.assertEquals(invalidated_count, 9)

  def test_invalidate_partial_identity_check(self):
    # Create a graph with a chain from A..Z.
    chain = self._mk_chain(self.pg, list('ABCDEFGHIJKLMNOPQRSTUVWXYZ'))
    self.assertTrue(list(self.pg.completed_nodes()))

    # Track the pre-invaliation nodes (from A..Q).
    index_of_q = chain.index('Q')
    before_nodes = [node for node, _ in self.pg.completed_nodes() if node in chain[:index_of_q + 1]]
    self.assertTrue(before_nodes)

    # Invalidate all nodes under Q.
    self.pg.invalidate(lambda node, _: node == chain[index_of_q])
    self.assertTrue(list(self.pg.completed_nodes()))

    # Check that the root node and all fs nodes were removed via a identity checks.
    for node, entry in self.pg._nodes.items():
      self.assertFalse(node in before_nodes, 'node:\n{}\nwasnt properly removed'.format(node))

      for associated in (entry.dependencies, entry.dependents, entry.cyclic_dependencies):
        for associated_entry in associated:
          self.assertFalse(
            associated_entry.node in before_nodes,
            'node:\n{}\nis still associated with:\n{}\nin {}'.format(node, associated_entry.node, entry)
          )
