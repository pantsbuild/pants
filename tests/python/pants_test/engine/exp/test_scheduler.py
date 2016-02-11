# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import unittest

import pytest

from pants.build_graph.address import Address
from pants.engine.exp.engine import LocalSerialEngine
from pants.engine.exp.examples.planners import (ApacheThriftJavaConfiguration, Classpath, GenGoal,
                                                Jar, JavaSources, ThriftSources, isolate_resources,
                                                ivy_resolve, javac, setup_json_scheduler)
from pants.engine.exp.scheduler import (BuildRequest, PartiallyConsumedInputsError, Return,
                                        SelectNode, Throw)


class SchedulerTest(unittest.TestCase):
  def setUp(self):
    build_root = os.path.join(os.path.dirname(__file__), 'examples', 'scheduler_inputs')
    self.scheduler = setup_json_scheduler(build_root)
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
    return list(self.scheduler.walk_product_graph(predicate=predicate))

  def assert_resolve_only(self, goals, root_specs, jars):
    build_request = BuildRequest(goals=goals,
                                 addressable_roots=[Address.parse(spec) for spec in root_specs])
    walk = self.build_and_walk(build_request)

    # Expect a SelectNode for each of the Jar/Classpath.
    self.assert_select_for_subjects(walk, Jar, jars)
    self.assert_select_for_subjects(walk, Classpath, jars)

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
    build_request = BuildRequest(goals=['gen'], addressable_roots=[self.java])
    walk = self.build_and_walk(build_request)

    self.assert_select_for_subjects(walk, JavaSources, [self.java])

  def test_gen(self):
    build_request = BuildRequest(goals=['gen'], addressable_roots=[self.thrift])
    walk = self.build_and_walk(build_request)

    # Root: expect the synthetic GenGoal product.
    root_entry = walk[0][0]
    self.assertEqual(SelectNode(self.thrift, GenGoal, None, None), root_entry[0])
    self.assertIsInstance(root_entry[1], Return)

    variants = {'thrift': 'apache_java'}
    # Expect ThriftSources to have been selected.
    self.assert_select_for_subjects(walk, ThriftSources, [self.thrift], variants=variants)
    # Expect an ApacheThriftJavaConfiguration to have been used via the default Variants.
    self.assert_select_for_subjects(walk, ApacheThriftJavaConfiguration, [self.thrift],
                                    variants=variants, variant_key='thrift')

  def test_codegen_simple(self):
    build_request = BuildRequest(goals=['compile'], addressable_roots=[self.java])
    walk = self.build_and_walk(build_request)

    # The subgraph below 'src/thrift/codegen/simple' will be affected by its default variants.
    subjects = [
        self.guava,
        self.java,
        self.thrift]
    variant_subjects = [
        Jar(org='org.apache.thrift', name='libthrift', rev='0.9.2'),
        Jar(org='commons-lang', name='commons-lang', rev='2.5'),
        Address.parse('src/thrift:slf4j-api')]

    # Root: expect compilation via javac.
    self.assertEqual((SelectNode(self.java, Classpath, None, None), Return(Classpath(creator='javac'))),
                     walk[0][0])

    # Confirm that exactly the expected subjects got Classpaths.
    self.assert_select_for_subjects(walk, Classpath, subjects)
    self.assert_select_for_subjects(walk, Classpath, variant_subjects,
                                    variants={'thrift': 'apache_java'})

  def test_consumes_resources(self):
    build_request = BuildRequest(goals=['compile'], addressable_roots=[self.consumes_resources])
    walk = self.build_and_walk(build_request)

    # Validate the root.
    self.assertEqual((SelectNode(self.consumes_resources, Classpath, None, None),
                      Return(Classpath(creator='javac'))),
                     walk[0][0])

    # Confirm a classpath for the resources target and other subjects. We know that they are
    # reachable from the root (since it was involved in this walk).
    subjects = [self.resources,
                self.consumes_resources,
                self.guava]
    self.assert_select_for_subjects(walk, Classpath, subjects)

  def test_managed_resolve(self):
    """A managed resolve should consume a ManagedResolve and ManagedJars to produce Jars."""
    build_request = BuildRequest(goals=['compile'],
                                 addressable_roots=[self.consumes_managed_thirdparty])
    walk = self.build_and_walk(build_request)

    # Validate the root.
    self.assertEqual((SelectNode(self.consumes_managed_thirdparty, Classpath, None, None),
                      Return(Classpath(creator='javac'))),
                     walk[0][0])

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
    build_request = BuildRequest(goals=['compile'],
                                 addressable_roots=[self.inferred_deps])
    walk = self.build_and_walk(build_request)

    # Validate the root.
    self.assertEqual((SelectNode(self.inferred_deps, Classpath, None, None),
                      Return(Classpath(creator='scalac'))),
                     walk[0][0])

    # Confirm that we requested a classpath for the root and inferred targets.
    self.assert_select_for_subjects(walk, Classpath, [self.inferred_deps, self.java_simple])

  def test_multiple_classpath_entries(self):
    """Multiple Classpath products for a single subject currently cause a failure."""
    build_request = BuildRequest(goals=['compile'], addressable_roots=[self.java_multi])
    walk = self.build_and_walk(build_request, failures=True)

    # Validate that the root failed.
    root_node, root_state = walk[0][0]
    self.assertEqual(SelectNode(self.java_multi, Classpath, None, None), root_node)
    self.assertEqual(Throw, type(root_state))

  def test_no_variant_thrift(self):
    """No `thrift` variant is configured, and so no configuration is selected."""
    build_request = BuildRequest(goals=['compile'],
                                 addressable_roots=[self.no_variant_thrift])

    with self.assertRaises(PartiallyConsumedInputsError):
      self.build_and_walk(build_request)

  def test_unconfigured_thrift(self):
    """The BuildPropertiesPlanner is able to produce a Classpath, but we should still fail.

    A target with ThriftSources doesn't have a thrift config: that input is partially consumed.
    """
    build_request = BuildRequest(goals=['compile'],
                                 addressable_roots=[self.unconfigured_thrift])

    with self.assertRaises(PartiallyConsumedInputsError):
      self.build_and_walk(build_request)
