# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import functools
import itertools
import os
import unittest

from pants.base.cmd_line_spec_parser import CmdLineSpecParser
from pants.build_graph.address import Address
from pants.engine.exp.addressable import Addresses
from pants.engine.exp.engine import LocalSerialEngine
from pants.engine.exp.examples.planners import (ApacheThriftJavaConfiguration, Classpath, GenGoal,
                                                Jar, JavaSources, ThriftSources,
                                                setup_json_scheduler)
from pants.engine.exp.nodes import (ConflictingProducersError, DependenciesNode, Return, SelectNode,
                                    Throw, Waiting)
from pants.engine.exp.scheduler import ProductGraph
from pants.util.contextutil import temporary_dir


class SchedulerTest(unittest.TestCase):
  def setUp(self):
    build_root = os.path.join(os.path.dirname(__file__), 'examples', 'scheduler_inputs')
    self.spec_parser = CmdLineSpecParser(build_root)
    self.scheduler, storage = setup_json_scheduler(build_root)
    self.storage = storage
    self.engine = LocalSerialEngine(self.scheduler, storage)

    self.guava = Address.parse('3rdparty/jvm:guava')
    self.thrift = Address.parse('src/thrift/codegen/simple')
    self.java = Address.parse('src/java/codegen/simple')
    self.java_simple = Address.parse('src/java/simple')
    self.java_multi = Address.parse('src/java/multiple_classpath_entries')
    self.no_variant_thrift = Address.parse('src/java/codegen/selector:conflict')
    self.unconfigured_thrift = Address.parse('src/thrift/codegen/unconfigured')
    self.resources = Address.parse('src/resources/simple')
    self.consumes_resources = Address.parse('src/java/consumes_resources')
    self.consumes_managed_thirdparty = Address.parse('src/java/managed_thirdparty')
    self.managed_guava = Address.parse('3rdparty/jvm/managed:guava')
    self.managed_hadoop = Address.parse('3rdparty/jvm/managed:hadoop-common')
    self.managed_resolve_latest = Address.parse('3rdparty/jvm/managed:latest-hadoop')
    self.inferred_deps = Address.parse('src/scala/inferred_deps')

  def assert_select_for_subjects(self, walk, product, subjects, variants=None, variant_key=None):
    node_type = SelectNode

    variants = tuple(variants.items()) if variants else None
    self.assertEqual({node_type(subject, product, variants, variant_key) for subject in subjects},
                     {node for (node, _), _ in walk
                      if node.product == product and isinstance(node, node_type) and node.variants == variants})

  def build_and_walk(self, build_request, failures=False):
    """Build and then walk the given build_request, returning the walked graph as a list."""
    predicate = (lambda _: True) if failures else None
    result = self.engine.execute(build_request)
    self.assertIsNone(result.error)
    return list(self.scheduler.product_graph.walk(build_request.roots, predicate=predicate))

  def request(self, goals, *addresses):
    return self.request_specs(goals, *[self.spec_parser.parse_spec(str(a)) for a in addresses])

  def request_specs(self, goals, *specs):
    return self.scheduler.build_request(goals=goals, subjects=specs)

  def assert_resolve_only(self, goals, root_specs, jars):
    build_request = self.request(goals, *root_specs)
    walk = self.build_and_walk(build_request)

    # Expect a SelectNode for each of the Jar/Classpath.
    self.assert_select_for_subjects(walk, Jar, jars)
    self.assert_select_for_subjects(walk, Classpath, jars)

  def assert_root(self, walk, node, return_value):
    """Asserts that the first Node in a walk was a DependenciesNode with the single given result."""
    ((root, root_state), dependencies) = walk[0]
    self.assertEquals(type(root), DependenciesNode)
    self.assertEquals(Return([return_value]), root_state)
    self.assertIn((node, Return(return_value)), dependencies)

  def assert_root_failed(self, walk, node, thrown_type):
    """Asserts that the first Node in a walk was a DependenciesNode with a Throw result."""
    ((root, root_state), dependencies) = walk[0]
    self.assertEquals(type(root), DependenciesNode)
    self.assertEquals(Throw, type(root_state))
    self.assertIn((node, thrown_type), [(k, type(v.exc))
                                        for k, v in dependencies if type(v) is Throw])

  def test_resolve(self):
    self.assert_resolve_only(goals=['resolve'],
                             root_specs=['3rdparty/jvm:guava'],
                             jars=[self.guava])

  def test_compile_only_3rdparty(self):
    self.assert_resolve_only(goals=['compile'],
                             root_specs=['3rdparty/jvm:guava'],
                             jars=[self.guava])

  def test_gen_noop(self):
    # TODO(John Sirois): Ask around - is this OK?
    # This is different than today.  There is a gen'able target reachable from the java target, but
    # the scheduler 'pull-seeding' has ApacheThriftPlanner stopping short since the subject it's
    # handed is not thrift.
    build_request = self.request(['gen'], self.java)
    walk = self.build_and_walk(build_request)

    self.assert_select_for_subjects(walk, JavaSources, [self.java])

  def test_gen(self):
    build_request = self.request(['gen'], self.thrift)
    walk = self.build_and_walk(build_request)

    # Root: expect the synthetic GenGoal product.
    self.assert_root(walk,
                     SelectNode(self.thrift, GenGoal, None, None),
                     GenGoal("non-empty input to satisfy the Goal constructor"))

    variants = {'thrift': 'apache_java'}
    # Expect ThriftSources to have been selected.
    self.assert_select_for_subjects(walk, ThriftSources, [self.thrift], variants=variants)
    # Expect an ApacheThriftJavaConfiguration to have been used via the default Variants.
    self.assert_select_for_subjects(walk, ApacheThriftJavaConfiguration, [self.thrift],
                                    variants=variants, variant_key='thrift')

  def test_codegen_simple(self):
    build_request = self.request(['compile'], self.java)
    walk = self.build_and_walk(build_request)

    # The subgraph below 'src/thrift/codegen/simple' will be affected by its default variants.
    subjects = [
        self.guava,
        self.java,
        self.thrift]
    variant_subjects = [
        Jar(org='org.apache.thrift', name='libthrift', rev='0.9.2', type_alias='jar'),
        Jar(org='commons-lang', name='commons-lang', rev='2.5', type_alias='jar'),
        Address.parse('src/thrift:slf4j-api')]

    # Root: expect a DependenciesNode depending on a SelectNode with compilation via javac.
    self.assert_root(walk,
                     SelectNode(self.java, Classpath, None, None),
                     Classpath(creator='javac'))

    # Confirm that exactly the expected subjects got Classpaths.
    self.assert_select_for_subjects(walk, Classpath, subjects)
    self.assert_select_for_subjects(walk, Classpath, variant_subjects,
                                    variants={'thrift': 'apache_java'})

  def test_consumes_resources(self):
    build_request = self.request(['compile'], self.consumes_resources)
    walk = self.build_and_walk(build_request)

    # Validate the root.
    self.assert_root(walk,
                     SelectNode(self.consumes_resources, Classpath, None, None),
                     Classpath(creator='javac'))

    # Confirm a classpath for the resources target and other subjects. We know that they are
    # reachable from the root (since it was involved in this walk).
    subjects = [self.resources,
                self.consumes_resources,
                self.guava]
    self.assert_select_for_subjects(walk, Classpath, subjects)

  def test_managed_resolve(self):
    """A managed resolve should consume a ManagedResolve and ManagedJars to produce Jars."""
    build_request = self.request(['compile'], self.consumes_managed_thirdparty)
    walk = self.build_and_walk(build_request)

    # Validate the root.
    self.assert_root(walk,
                     SelectNode(self.consumes_managed_thirdparty, Classpath, None, None),
                     Classpath(creator='javac'))

    # Confirm that we produced classpaths for the managed jars.
    managed_jars = [self.managed_guava,
                    self.managed_hadoop]
    self.assert_select_for_subjects(walk, Classpath, [self.consumes_managed_thirdparty])
    self.assert_select_for_subjects(walk, Classpath, managed_jars, variants={'resolve': 'latest-hadoop'})

    # Confirm that the produced jars had the appropriate versions.
    self.assertEquals({Jar('org.apache.hadoop', 'hadoop-common', '2.7.0'),
                       Jar('com.google.guava', 'guava', '18.0')},
                      {ret.value for (node, ret), _ in walk
                       if node.product == Jar and isinstance(node, SelectNode)})

  def test_dependency_inference(self):
    """Scala dependency inference introduces dependencies that do not exist in BUILD files."""
    build_request = self.request(['compile'], self.inferred_deps)
    walk = self.build_and_walk(build_request)

    # Validate the root.
    self.assert_root(walk,
                     SelectNode(self.inferred_deps, Classpath, None, None),
                     Classpath(creator='scalac'))

    # Confirm that we requested a classpath for the root and inferred targets.
    self.assert_select_for_subjects(walk, Classpath, [self.inferred_deps, self.java_simple])

  def test_multiple_classpath_entries(self):
    """Multiple Classpath products for a single subject currently cause a failure."""
    build_request = self.request(['compile'], self.java_multi)
    walk = self.build_and_walk(build_request, failures=True)

    # Validate that the root failed.
    self.assert_root_failed(walk,
                            SelectNode(self.java_multi, Classpath, None, None),
                            ConflictingProducersError)

  def test_descendant_specs(self):
    """Test that Addresses are produced via recursive globs of the 3rdparty/jvm directory."""
    spec = self.spec_parser.parse_spec('3rdparty/jvm::')
    build_request = self.request_specs(['list'], spec)
    walk = self.build_and_walk(build_request)

    # Validate the root.
    root, root_state = walk[0][0]
    root_value = root_state.value
    self.assertEqual(DependenciesNode(spec, Address, None, Addresses, None), root)
    self.assertEqual(list, type(root_value))

    # Confirm that a few expected addresses are in the list.
    self.assertIn(self.guava, root_value)
    self.assertIn(self.managed_guava, root_value)
    self.assertIn(self.managed_resolve_latest, root_value)

  def test_sibling_specs(self):
    """Test that sibling Addresses are parsed in the 3rdparty/jvm directory."""
    spec = self.spec_parser.parse_spec('3rdparty/jvm:')
    build_request = self.request_specs(['list'], spec)
    walk = self.build_and_walk(build_request)

    # Validate the root.
    root, root_state = walk[0][0]
    root_value = root_state.value
    self.assertEqual(DependenciesNode(spec, Address, None, Addresses, None), root)
    self.assertEqual(list, type(root_value))

    # Confirm that an expected address is in the list.
    self.assertIn(self.guava, root_value)
    # And that an subdirectory address is not.
    self.assertNotIn(self.managed_guava, root_value)

  def test_scheduler_visualize(self):
    spec = self.spec_parser.parse_spec('3rdparty/jvm:')
    build_request = self.request_specs(['list'], spec)
    self.build_and_walk(build_request)

    graphviz_output = '\n'.join(self.scheduler.product_graph.visualize(build_request.roots))

    with temporary_dir() as td:
      output_path = os.path.join(td, 'output.dot')
      self.scheduler.visualize_graph_to_file(build_request.roots, output_path)
      with open(output_path, 'rb') as fh:
        graphviz_disk_output = fh.read().strip()

    self.assertEqual(graphviz_output, graphviz_disk_output)
    self.assertIn('digraph', graphviz_output)
    self.assertIn(' -> ', graphviz_output)


# TODO: Expand test coverage here.
class ProductGraphTest(unittest.TestCase):
  def setUp(self):
    self.pg = ProductGraph(validator=lambda _: True)  # Allow for string nodes for testing.

  @classmethod
  def _mk_chain(cls, graph, sequence, states=[Waiting, Return]):
    """Create a chain of dependencies (e.g. 'A'->'B'->'C'->'D') in the graph from a sequence."""
    prior_item = sequence[0]
    for state in states:
      for item in sequence:
        graph.update_state(prior_item, state([item]))
        prior_item = item
    return sequence

  def test_dependency_edges(self):
    self.pg.update_state('A', Waiting(['B', 'C']))
    self.assertEquals({'B', 'C'}, self.pg.dependencies_of('A'))
    self.assertEquals({'A'}, self.pg.dependents_of('B'))
    self.assertEquals({'A'}, self.pg.dependents_of('C'))

  def test_walk(self):
    nodes = list('ABCDEF')
    self._mk_chain(self.pg, nodes)
    walked_nodes = list((node for (node, _), _ in self.pg.walk(nodes[0])))
    self.assertEquals(nodes, walked_nodes)

  def test_invalidate_all(self):
    chain_list = list('ABCDEFGHIJKLMNOPQRSTUVWXYZ')
    invalidators = (
      self.pg.invalidate,
      functools.partial(self.pg.invalidate, lambda node: node == 'Z')
    )

    for invalidator in invalidators:
      self._mk_chain(self.pg, chain_list)

      self.assertTrue(self.pg.completed_nodes())
      self.assertTrue(self.pg.dependents())
      self.assertTrue(self.pg.dependencies())
      self.assertTrue(self.pg.cyclic_dependencies())

      invalidator()

      self.assertFalse(self.pg.completed_nodes())
      self.assertFalse(self.pg.dependents())
      self.assertFalse(self.pg.dependencies())
      self.assertFalse(self.pg.cyclic_dependencies())

  def test_invalidate_partial(self):
    comparison_pg = ProductGraph(validator=lambda _: True)
    chain_a = list('ABCDEF')
    chain_b = list('GHIJKL')

    # Add two dependency chains to the primary graph.
    self._mk_chain(self.pg, chain_a)
    self._mk_chain(self.pg, chain_b)

    # Add only the dependency chain we won't invalidate to the comparison graph.
    self._mk_chain(comparison_pg, chain_b)

    # Invalidate one of the chains in the primary graph from the right-most node.
    self.pg.invalidate(lambda node: node == chain_a[-1])

    # Ensure the final state of the primary graph matches the comparison graph.
    self.assertEquals(self.pg.completed_nodes(), comparison_pg.completed_nodes())
    self.assertEquals(self.pg.dependents(), comparison_pg.dependents())
    self.assertEquals(self.pg.dependencies(), comparison_pg.dependencies())
    self.assertEquals(self.pg.cyclic_dependencies(), comparison_pg.cyclic_dependencies())

  def test_invalidate_count(self):
    self._mk_chain(self.pg, list('ABCDEFGHIJKLMNOPQRSTUVWXYZ'))
    invalidated_count = self.pg.invalidate(lambda node: node == 'I')
    self.assertEquals(invalidated_count, 9)

  def test_invalidate_partial_identity_check(self):
    # Create a graph with a chain from A..Z.
    chain = self._mk_chain(self.pg, list('ABCDEFGHIJKLMNOPQRSTUVWXYZ'))
    self.assertTrue(self.pg.completed_nodes())

    # Track the pre-invaliation nodes (from A..Q).
    index_of_q = chain.index('Q')
    before_nodes = filter(lambda node: node in chain[:index_of_q + 1], self.pg.completed_nodes())
    self.assertTrue(before_nodes)

    # Invalidate all nodes under Q.
    self.pg.invalidate(lambda node: node == chain[index_of_q])
    self.assertTrue(self.pg.completed_nodes())

    def _label_tuples(collection, name):
      for item in collection:
        yield tuple(list(item) + [name])

    # Check that the root node and all fs nodes were removed via a identity checks.
    chain = itertools.chain(
      _label_tuples(self.pg.completed_nodes().items(), 'completed_nodes'),
      _label_tuples(self.pg.dependents().items(), 'dependents'),
      _label_tuples(self.pg.dependencies().items(), 'dependencies'),
      _label_tuples(self.pg.cyclic_dependencies().items(), 'cyclic_dependencies')
    )

    for node, associated, collection_name in chain:
      self.assertFalse(
        node in before_nodes,
        'node:\n{}\nwasnt properly removed from {}'.format(node, collection_name)
      )

      if isinstance(associated, set):
        for associated_node in associated:
          self.assertFalse(
            associated_node in before_nodes,
            'node:\n{}\nis still associated with:\n{}\nin {}'.format(associated_node,
                                                                     node,
                                                                     collection_name)
          )
