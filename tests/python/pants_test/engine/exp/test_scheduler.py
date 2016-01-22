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
from pants.engine.exp.examples.planners import (Classpath, Jar, JavaSources, gen_apache_thrift,
                                                isolate_resources, ivy_resolve, javac,
                                                setup_json_scheduler)
from pants.engine.exp.scheduler import (BuildRequest, ConflictingProducersError,
                                        PartiallyConsumedInputsError, Return, SelectNode)


class SchedulerTest(unittest.TestCase):
  def setUp(self):
    build_root = os.path.join(os.path.dirname(__file__), 'examples', 'scheduler_inputs')
    self.graph, self.scheduler = setup_json_scheduler(build_root)
    self.engine = LocalSerialEngine(self.scheduler)

    self.guava = self.graph.resolve(Address.parse('3rdparty/jvm:guava'))
    self.thrift = self.graph.resolve(Address.parse('src/thrift/codegen/simple'))
    self.java = self.graph.resolve(Address.parse('src/java/codegen/simple'))
    self.java_multi = self.graph.resolve(Address.parse('src/java/multiple_classpath_entries'))
    self.unconfigured_thrift = self.graph.resolve(Address.parse('src/thrift/codegen/unconfigured'))
    self.resources = self.graph.resolve(Address.parse('src/resources/simple'))
    self.consumes_resources = self.graph.resolve(Address.parse('src/java/consumes_resources'))

  def assert_product_for_subjects(self, walk, product, subjects):
    self.assertEqual({SelectNode(subject, product, None) for subject in subjects},
                     {node for (node, _), _ in walk
                      if node.product == product and isinstance(node, SelectNode)})

  def build_and_walk(self, build_request):
    """Build and then walk the given build_request, returning the walked graph as a list."""
    result = self.engine.execute(build_request)
    self.assertIsNone(result.error)
    walk = list(self.scheduler.walk_product_graph())
    for entry in walk:
      print('>>> {}'.format(entry))
    return walk

  def assert_resolve_only(self, goals, root_specs, jars):
    build_request = BuildRequest(goals=goals,
                                 addressable_roots=[Address.parse(spec) for spec in root_specs])
    walk = self.build_and_walk(build_request)

    # Expect a SelectNode for each of the Jar and Classpath, and a TaskNode and NativeNode.
    self.assertEqual(4 * len(jars), len(walk))
    self.assert_product_for_subjects(walk, Jar, jars)
    self.assert_product_for_subjects(walk, Classpath, jars)

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
    build_request = BuildRequest(goals=['gen'], addressable_roots=[self.java.address])
    walk = self.build_and_walk(build_request)

    self.assertEqual(1, len(walk))

    self.assertEqual((JavaSources,
                      Plan(func_or_task_type=lift_native_product,
                           subjects=[self.java],
                           subject=self.java,
                           product_type=JavaSources)),
                     self.extract_product_type_and_plan(plans[0]))

  def test_gen(self):
    build_request = BuildRequest(goals=['gen'], addressable_roots=[self.thrift.address])
    walk = self.build_and_walk(build_request)

    self.assertEqual(1, len(walk))

    self.assertEqual((JavaSources,
                      Plan(func_or_task_type=gen_apache_thrift,
                           subjects=[self.thrift],
                           strict=True,
                           rev='0.9.2',
                           gen='java',
                           sources=['src/thrift/codegen/simple/simple.thrift'])),
                     self.extract_product_type_and_plan(plans[0]))

  def test_codegen_simple(self):
    build_request = BuildRequest(goals=['compile'], addressable_roots=[self.java.address])
    walk = self.build_and_walk(build_request)

    self.assertEqual(29, len(walk))

    subjects = [self.guava,
                Jar(org='org.apache.thrift', name='libthrift', rev='0.9.2'),
                Jar(org='commons-lang', name='commons-lang', rev='2.5'),
                self.graph.resolve(Address.parse('src/thrift:slf4j-api')),
                self.java,
                self.thrift]

    # Root: expect compilation via javac.
    self.assertEqual((SelectNode(self.java, Classpath, None), Return(Classpath(creator='javac'))),
                     walk[0][0])

    # Confirm that exactly the expected subjects got Classpaths.
    self.assert_product_for_subjects(walk, Classpath, subjects)

  def test_consumes_resources(self):
    build_request = BuildRequest(goals=['compile'], addressable_roots=[self.consumes_resources.address])
    walk = self.build_and_walk(build_request)

    self.assertEqual(13, len(walk))

    # Validate the root.
    self.assertEqual((SelectNode(self.consumes_resources, Classpath, None),
                      Return(Classpath(creator='javac'))),
                     walk[0][0])

    # Confirm a classpath for the resources target and other subjects. We know that they are
    # reachable from the root (since it was involved in this walk).
    subjects = [self.resources,
                self.consumes_resources,
                self.guava]
    self.assert_product_for_subjects(walk, Classpath, subjects)

  @pytest.mark.xfail(raises=ConflictingProducersError)
  def test_multiple_classpath_entries(self):
    """Multiple Classpath products for a single subject currently cause a failure."""
    build_request = BuildRequest(goals=['compile'], addressable_roots=[self.java_multi.address])
    walk = self.build_and_walk(build_request)

  def test_no_configured_thrift_planner(self):
    """Tests that even though the BuildPropertiesPlanner is able to produce a Classpath,
    we still fail when a target with thrift sources doesn't have a thrift config.
    """
    build_request = BuildRequest(goals=['compile'],
                                 addressable_roots=[self.unconfigured_thrift.address])
    with self.assertRaises(PartiallyConsumedInputsError):
      self.build_and_walk(build_request)
