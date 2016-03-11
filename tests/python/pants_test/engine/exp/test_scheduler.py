# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import unittest

import pytest

from pants.base.cmd_line_spec_parser import CmdLineSpecParser
from pants.build_graph.address import Address
from pants.engine.exp.addressable import Addresses
from pants.engine.exp.engine import LocalSerialEngine
from pants.engine.exp.examples.planners import (ApacheThriftJavaConfiguration, Classpath, GenGoal,
                                                Jar, JavaSources, ThriftSources,
                                                setup_json_scheduler)
from pants.engine.exp.nodes import (ConflictingProducersError, DependenciesNode, Return, SelectNode,
                                    Throw)
from pants.engine.exp.scheduler import PartiallyConsumedInputsError


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

  def key(self, subject):
    return self.storage.put(subject)

  def assert_select_for_subjects(self, walk, product, subjects, variants=None, variant_key=None):
    node_type = SelectNode

    variants = tuple(variants.items()) if variants else None
    self.assertEqual({node_type(self.key(subject), product, variants, variant_key) for subject in subjects},
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
    return self.scheduler.build_request(goals=goals, subject_keys=self.storage.puts(specs))

  def assert_resolve_only(self, goals, root_specs, jars):
    build_request = self.request(goals, *root_specs)
    walk = self.build_and_walk(build_request)

    # Expect a SelectNode for each of the Jar/Classpath.
    self.assert_select_for_subjects(walk, Jar, jars)
    self.assert_select_for_subjects(walk, Classpath, jars)

  def assert_root(self, walk, node, return_value):
    """Asserts that the first Node in a walk was a DependenciesNode with the single given result."""
    ((root, root_state_key), dependencies) = walk[0]
    self.assertEquals(type(root), DependenciesNode)
    self.assertEquals(Return([return_value]), self.storage.get(root_state_key))
    self.assertIn((node, self.key(Return(return_value))), dependencies)

  def assert_root_failed(self, walk, node, thrown_type):
    """Asserts that the first Node in a walk was a DependenciesNode with a Throw result."""
    ((root, root_state), dependencies) = walk[0]
    self.assertEquals(type(root), DependenciesNode)
    self.assertEquals(Throw, root_state.type)
    self.assertIn((node, thrown_type), [(k, type(self.storage.get(v).exc))
                                        for k, v in dependencies if v.type is Throw])

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
                     SelectNode(self.key(self.thrift), GenGoal, None, None),
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

    # TODO: Utter insanity. Pickle only encodes a unique object (ie, `if A is B`) a single
    # time on the wire. Because the copy of this object that we're comparing to is coming
    # from a file, the string will be encoded twice. Thus, to match (with pickle) we need
    # to ensure that `(cl1 is not cl2)` here. See:
    #   https://github.com/pantsbuild/pants/issues/2969
    cl1 = 'commons-lang'
    cl2 = 'commons' + '-lang'

    # The subgraph below 'src/thrift/codegen/simple' will be affected by its default variants.
    subjects = [
        self.guava,
        self.java,
        self.thrift]
    variant_subjects = [
        Jar(org='org.apache.thrift', name='libthrift', rev='0.9.2', type_alias='jar'),
        Jar(org=cl1, name=cl2, rev='2.5', type_alias='jar'),
        Address.parse('src/thrift:slf4j-api')]

    # Root: expect a DependenciesNode depending on a SelectNode with compilation via javac.
    self.assert_root(walk,
                     SelectNode(self.key(self.java), Classpath, None, None),
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
                     SelectNode(self.key(self.consumes_resources), Classpath, None, None),
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
                     SelectNode(self.key(self.consumes_managed_thirdparty), Classpath, None, None),
                     Classpath(creator='javac'))

    # Confirm that we produced classpaths for the managed jars.
    managed_jars = [self.managed_guava,
                    self.managed_hadoop]
    self.assert_select_for_subjects(walk, Classpath, [self.consumes_managed_thirdparty])
    self.assert_select_for_subjects(walk, Classpath, managed_jars, variants={'resolve': 'latest-hadoop'})

    # Confirm that the produced jars had the appropriate versions.
    self.assertEquals({Jar('org.apache.hadoop', 'hadoop-common', '2.7.0'),
                       Jar('com.google.guava', 'guava', '18.0')},
                      {self.storage.get(ret).value for (node, ret), _ in walk
                       if node.product == Jar and isinstance(node, SelectNode)})

  @pytest.mark.xfail(reason='TODO: see https://github.com/pantsbuild/pants/issues/3024')
  def test_dependency_inference(self):
    """Scala dependency inference introduces dependencies that do not exist in BUILD files."""
    build_request = self.request(['compile'], self.inferred_deps)
    walk = self.build_and_walk(build_request)

    # Validate the root.
    self.assert_root(walk,
                     SelectNode(self.key(self.inferred_deps), Classpath, None, None),
                     Classpath(creator='scalac'))

    # Confirm that we requested a classpath for the root and inferred targets.
    self.assert_select_for_subjects(walk, Classpath, [self.inferred_deps, self.java_simple])

  def test_multiple_classpath_entries(self):
    """Multiple Classpath products for a single subject currently cause a failure."""
    build_request = self.request(['compile'], self.java_multi)
    walk = self.build_and_walk(build_request, failures=True)

    # Validate that the root failed.
    self.assert_root_failed(walk,
                            SelectNode(self.key(self.java_multi), Classpath, None, None),
                            ConflictingProducersError)

  def test_no_variant_thrift(self):
    """No `thrift` variant is configured, and so no configuration is selected."""
    build_request = self.request(['compile'], self.no_variant_thrift)

    with self.assertRaises(PartiallyConsumedInputsError):
      self.build_and_walk(build_request)

  def test_unconfigured_thrift(self):
    """The BuildPropertiesPlanner is able to produce a Classpath, but we should still fail.

    A target with ThriftSources doesn't have a thrift config: that input is partially consumed.
    """
    build_request = self.request(['compile'], self.unconfigured_thrift)

    with self.assertRaises(PartiallyConsumedInputsError):
      self.build_and_walk(build_request)

  def test_descendant_specs(self):
    """Test that Addresses are produced via recursive globs of the 3rdparty/jvm directory."""
    spec = self.spec_parser.parse_spec('3rdparty/jvm::')
    build_request = self.request_specs(['list'], spec)
    walk = self.build_and_walk(build_request)

    # Validate the root.
    root, root_state_key = walk[0][0]
    root_value = self.storage.get(root_state_key).value
    self.assertEqual(DependenciesNode(self.key(spec), Address, None, Addresses, None), root)
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
    root, root_state_key = walk[0][0]
    root_value = self.storage.get(root_state_key).value
    self.assertEqual(DependenciesNode(self.key(spec), Address, None, Addresses, None), root)
    self.assertEqual(list, type(root_value))

    # Confirm that an expected address is in the list.
    self.assertIn(self.guava, root_value)
    # And that an subdirectory address is not.
    self.assertNotIn(self.managed_guava, root_value)
