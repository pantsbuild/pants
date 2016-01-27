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
from pants.engine.exp.examples.planners import (ApacheThriftJavaConfiguration, Classpath, Jar,
                                                JavaSources, isolate_resources, ivy_resolve, javac,
                                                setup_json_scheduler)
from pants.engine.exp.scheduler import (BuildRequest, ConflictingProducersError,
                                        PartiallyConsumedInputsError, Return, SelectNode)


class SchedulerTest(unittest.TestCase):
  def setUp(self):
    build_root = os.path.join(os.path.dirname(__file__), 'examples', 'scheduler_inputs')
    self.scheduler = setup_json_scheduler(build_root)
    self.engine = LocalSerialEngine(self.scheduler)

    self.guava = Address.parse('3rdparty/jvm:guava')
    self.thrift = Address.parse('src/thrift/codegen/simple')
    self.java = Address.parse('src/java/codegen/simple')
    self.java_multi = Address.parse('src/java/multiple_classpath_entries')
    self.unconfigured_thrift = Address.parse('src/thrift/codegen/unconfigured')
    self.resources = Address.parse('src/resources/simple')
    self.consumes_resources = Address.parse('src/java/consumes_resources')
    self.consumes_managed_thirdparty = Address.parse('src/java/managed_thirdparty')
    self.managed_guava = Address.parse('3rdparty/jvm/managed:guava')
    self.managed_hadoop = Address.parse('3rdparty/jvm/managed:hadoop-common')

  def assert_select_for_subjects(self, walk, product, subjects, variants=None, variant=None):
    node_type = SelectNode
    variants = tuple(variants.items()) if variants else None
    self.assertEqual({node_type(subject, product, variants, variant) for subject in subjects},
                     {node for (node, _), _ in walk
                      if node.product == product and isinstance(node, node_type) and node.variants == variants})

  def build_and_walk(self, build_request):
    """Build and then walk the given build_request, returning the walked graph as a list."""
    result = self.engine.execute(build_request)
    self.assertIsNone(result.error)
    return list(self.scheduler.walk_product_graph())

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

    # Root: expect JavaSources.
    root_entry = walk[0][0]
    self.assertEqual(SelectNode(self.thrift, JavaSources, None, None), root_entry[0])
    self.assertIsInstance(root_entry[1], Return)

    # Expect an ApacheThriftJavaConfiguration to have been used.
    self.assert_select_for_subjects(walk, ApacheThriftJavaConfiguration, [self.thrift])

  def test_codegen_simple(self):
    build_request = BuildRequest(goals=['compile'], addressable_roots=[self.java])
    walk = self.build_and_walk(build_request)

    subjects = [self.guava,
                Jar(org='org.apache.thrift', name='libthrift', rev='0.9.2'),
                Jar(org='commons-lang', name='commons-lang', rev='2.5'),
                Address.parse('src/thrift:slf4j-api'),
                self.java,
                self.thrift]

    # Root: expect compilation via javac.
    self.assertEqual((SelectNode(self.java, Classpath, None, None), Return(Classpath(creator='javac'))),
                     walk[0][0])

    # Confirm that exactly the expected subjects got Classpaths.
    self.assert_select_for_subjects(walk, Classpath, subjects)

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

  @pytest.mark.xfail(raises=ConflictingProducersError)
  def test_multiple_classpath_entries(self):
    """Multiple Classpath products for a single subject currently cause a failure."""
    build_request = BuildRequest(goals=['compile'], addressable_roots=[self.java_multi])
    walk = self.build_and_walk(build_request)

  @pytest.mark.xfail(raises=PartiallyConsumedInputsError)
  def test_no_configured_thrift_planner(self):
    """Even though the BuildPropertiesPlanner is able to produce a Classpath,
    we still fail when a target with thrift sources doesn't have a thrift config.
    """
    build_request = BuildRequest(goals=['compile'],
                                 addressable_roots=[self.unconfigured_thrift])
    walk = self.build_and_walk(build_request)
