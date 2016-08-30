# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import functools
import os
import unittest

from pants.base.cmd_line_spec_parser import CmdLineSpecParser
from pants.build_graph.address import Address
from pants.engine.addressable import Addresses
from pants.engine.engine import LocalSerialEngine
from pants.engine.nodes import (ConflictingProducersError, DependenciesNode, Return, SelectNode,
                                Throw, Waiting)
from pants.engine.rules import NodeBuilder, RulesetValidator
from pants.engine.scheduler import (CompletedNodeException, IncompleteDependencyException,
                                    ProductGraph)
from pants.engine.selectors import Select, SelectDependencies, SelectVariant
from pants.util.contextutil import temporary_dir
from pants_test.engine.examples.planners import (ApacheThriftJavaConfiguration, Classpath, GenGoal,
                                                 Goal, Jar, JavaSources, ThriftSources,
                                                 setup_json_scheduler)


class SchedulerTest(unittest.TestCase):
  def setUp(self):
    build_root = os.path.join(os.path.dirname(__file__), 'examples', 'scheduler_inputs')
    self.spec_parser = CmdLineSpecParser(build_root)
    self.scheduler = setup_json_scheduler(build_root, inline_nodes=False)
    self.pg = self.scheduler.product_graph
    self.engine = LocalSerialEngine(self.scheduler)

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

  def assert_select_for_subjects(self, walk, selector, subjects, variants=None):
    node_type = SelectNode

    variants = tuple(variants.items()) if variants else None
    self.assertEqual(list({node_type(subject, variants, selector) for subject in subjects}),
      list({node for node, _ in walk
                      if isinstance(node, node_type) and
                         node.selector == selector and
                         node.variants == variants}))

  def build_and_walk(self, build_request):
    """Build and then walk the given build_request, returning the walked graph as a list."""
    result = self.engine.execute(build_request)
    self.assertIsNone(result.error)
    return list(self.scheduler.product_graph.walk(build_request.roots))

  def request(self, goals, *addresses):
    return self.request_specs(goals, *[self.spec_parser.parse_spec(str(a)) for a in addresses])

  def request_specs(self, goals, *specs):
    return self.scheduler.build_request(goals=goals, subjects=specs)

  def assert_resolve_only(self, goals, root_specs, jars):
    build_request = self.request(goals, *root_specs)
    walk = self.build_and_walk(build_request)

    # Expect a SelectNode for each of the Jar/Classpath.
    self.assert_select_for_subjects(walk, Select(Jar), jars)
    self.assert_select_for_subjects(walk, Select(Classpath), jars)

  def assert_root(self, walk, node, return_value):
    """Asserts that the first Node in a walk was a DependenciesNode with the single given result."""
    root, root_state = walk[0]
    self.assertEquals(type(root), DependenciesNode)
    self.assertEquals(Return([return_value]), root_state)
    self.assertIn((node, Return(return_value)),
                  [(d, self.pg.state(d)) for d in self.pg.dependencies_of(root)])

  def assert_root_failed(self, walk, node, thrown_type):
    """Asserts that the first Node in a walk was a DependenciesNode with a Throw result."""
    root, root_state = walk[0]
    self.assertEquals(type(root), DependenciesNode)
    self.assertEquals(Throw, type(root_state))
    dependencies = [(d, self.pg.state(d)) for d in self.pg.dependencies_of(root)]
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

    self.assert_select_for_subjects(walk, Select(JavaSources, optional=True), [self.java])

  def test_gen(self):
    build_request = self.request(['gen'], self.thrift)
    walk = self.build_and_walk(build_request)

    # Root: expect the synthetic GenGoal product.
    self.assert_root(walk,
                     SelectNode(self.thrift, None, Select(GenGoal)),
                     GenGoal("non-empty input to satisfy the Goal constructor"))

    variants = {'thrift': 'apache_java'}
    # Expect ThriftSources to have been selected.
    self.assert_select_for_subjects(walk, Select(ThriftSources), [self.thrift], variants=variants)
    # Expect an ApacheThriftJavaConfiguration to have been used via the default Variants.
    self.assert_select_for_subjects(walk, SelectVariant(ApacheThriftJavaConfiguration,
                                                        variant_key='thrift'),
                                    [self.thrift],
                                    variants=variants)

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
                     SelectNode(self.java, None, Select(Classpath)),
                     Classpath(creator='javac'))

    # Confirm that exactly the expected subjects got Classpaths.
    self.assert_select_for_subjects(walk, Select(Classpath), subjects)
    self.assert_select_for_subjects(walk, Select(Classpath), variant_subjects,
                                    variants={'thrift': 'apache_java'})

  def test_consumes_resources(self):
    build_request = self.request(['compile'], self.consumes_resources)
    walk = self.build_and_walk(build_request)

    # Validate the root.
    self.assert_root(walk,
                     SelectNode(self.consumes_resources, None, Select(Classpath)),
                     Classpath(creator='javac'))

    # Confirm a classpath for the resources target and other subjects. We know that they are
    # reachable from the root (since it was involved in this walk).
    subjects = [self.resources,
                self.consumes_resources,
                self.guava]
    self.assert_select_for_subjects(walk, Select(Classpath), subjects)

  def test_managed_resolve(self):
    """A managed resolve should consume a ManagedResolve and ManagedJars to produce Jars."""
    build_request = self.request(['compile'], self.consumes_managed_thirdparty)
    walk = self.build_and_walk(build_request)

    # Validate the root.
    self.assert_root(walk,
                     SelectNode(self.consumes_managed_thirdparty, None, Select(Classpath)),
                     Classpath(creator='javac'))

    # Confirm that we produced classpaths for the managed jars.
    managed_jars = [self.managed_guava,
                    self.managed_hadoop]
    self.assert_select_for_subjects(walk, Select(Classpath), [self.consumes_managed_thirdparty])
    self.assert_select_for_subjects(walk, Select(Classpath), managed_jars,
                                    variants={'resolve': 'latest-hadoop'})

    # Confirm that the produced jars had the appropriate versions.
    self.assertEquals({Jar('org.apache.hadoop', 'hadoop-common', '2.7.0'),
                       Jar('com.google.guava', 'guava', '18.0')},
                      {ret.value for node, ret in walk
                       if node.product == Jar and isinstance(node, SelectNode)})

  def test_dependency_inference(self):
    """Scala dependency inference introduces dependencies that do not exist in BUILD files."""
    build_request = self.request(['compile'], self.inferred_deps)
    walk = self.build_and_walk(build_request)

    # Validate the root.
    self.assert_root(walk,
                     SelectNode(self.inferred_deps, None, Select(Classpath)),
                     Classpath(creator='scalac'))

    # Confirm that we requested a classpath for the root and inferred targets.
    self.assert_select_for_subjects(walk, Select(Classpath), [self.inferred_deps, self.java_simple])

  def test_multiple_classpath_entries(self):
    """Multiple Classpath products for a single subject currently cause a failure."""
    build_request = self.request(['compile'], self.java_multi)
    walk = self.build_and_walk(build_request)

    # Validate that the root failed.
    self.assert_root_failed(walk,
                            SelectNode(self.java_multi, None, Select(Classpath)),
                            ConflictingProducersError)

  def test_descendant_specs(self):
    """Test that Addresses are produced via recursive globs of the 3rdparty/jvm directory."""
    spec = self.spec_parser.parse_spec('3rdparty/jvm::')
    build_request = self.request_specs(['list'], spec)
    walk = self.build_and_walk(build_request)

    # Validate the root.
    root, root_state = walk[0]
    root_value = root_state.value
    self.assertEqual(DependenciesNode(spec,
                                      None,
                                      SelectDependencies(Address, Addresses, field_types=(Address,))),
                     root)
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
    root, root_state = walk[0]
    root_value = root_state.value
    self.assertEqual(DependenciesNode(spec,
                                      None,
                                      SelectDependencies(Address, Addresses, field_types=(Address,))),
                     root)
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
    for state in states:
      dest = None
      for src in reversed(sequence):
        if state is Waiting:
          graph.add_dependencies(src, [dest] if dest else [])
        else:
          graph.complete_node(src, state([dest]))
        dest = src
    return sequence

  def test_disallow_completed_state_change(self):
    self.pg.complete_node('A', Return('done!'))
    with self.assertRaises(CompletedNodeException):
      self.pg.add_dependencies('A', ['B'])

  def test_disallow_completing_with_incomplete_deps(self):
    self.pg.add_dependencies('A', ['B'])
    self.pg.add_dependencies('B', ['C'])
    with self.assertRaises(IncompleteDependencyException):
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
    self._mk_chain(self.pg, nodes, states=(Waiting,))
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
    comparison_pg = ProductGraph(validator=lambda _: True)
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


class AGoal(Goal):

  @classmethod
  def products(cls):
    return [A]


class A(object):
  pass


class B(object):
  pass


def noop(*args):
  pass


class SubA(A):
  pass


class RulesetValidatorTest(unittest.TestCase):
  def test_ruleset_with_missing_product_type(self):
    validator = RulesetValidator(NodeBuilder.create([(A, (Select(B),), noop)]),
      goal_to_product=dict(),
      root_subject_types=tuple())
    with self.assertRaises(ValueError):
      validator.validate()

  def test_ruleset_with_with_selector_only_provided_as_root_subject(self):

    validator = RulesetValidator(NodeBuilder.create([(A, (Select(B),), noop)]),
      goal_to_product=dict(),
      root_subject_types=(B,))

    validator.validate()

  def test_ruleset_with_superclass_of_selected_type_produced(self):

    rules = [
      (A, (Select(B),), noop),
      (B, (Select(SubA),), noop)
    ]
    validator = RulesetValidator(NodeBuilder.create(rules),
      goal_to_product=dict(),
      root_subject_types=tuple())

    validator.validate()

  def test_ruleset_with_goal_not_produced(self):

    rules = [
      (B, (Select(SubA),), noop)
    ]
    validator = RulesetValidator(NodeBuilder.create(rules),
      goal_to_product={'goal-name': AGoal},
      root_subject_types=tuple())
    with self.assertRaises(ValueError):
      validator.validate()

      # products that are not used
      # selectors of different types that cannot be provided
      # maybe this needs to be a separate type.
      # :/
      #def test_ruleset_with_no_usage_of_product_type(self):
      #  class A(object):
      #    pass
      #  class B(object):
      #    pass
      #  def noop(*args):
      #    pass
      #
      #  with self.assertRaises(ValueError):
      #    RulesetValidator(NodeBuilder.create([(A, (Select(B),), noop)]), None, None)
      #
