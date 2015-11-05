# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import unittest

import pytest

from pants.build_graph.address import Address
from pants.engine.exp.examples.planners import (Classpath, IvyResolve, Jar, Javac, Sources,
                                                gen_apache_thrift, setup_json_scheduler)
from pants.engine.exp.scheduler import BuildRequest, ConflictingProducersError, Plan, Promise


class SchedulerTest(unittest.TestCase):
  def setUp(self):
    build_root = os.path.join(os.path.dirname(__file__), 'examples', 'scheduler_inputs')
    self.graph, self.scheduler = setup_json_scheduler(build_root)

    self.guava = self.graph.resolve(Address.parse('3rdparty/jvm:guava'))
    self.thrift = self.graph.resolve(Address.parse('src/thrift/codegen/simple'))
    self.java = self.graph.resolve(Address.parse('src/java/codegen/simple'))
    self.java_multi = self.graph.resolve(Address.parse('src/java/multiple_classpath_entries'))

  def extract_product_type_and_plan(self, plan):
    promise, plan = plan
    return promise.product_type, plan

  def assert_resolve_only(self, goals, root_specs, jars):
    build_request = BuildRequest(goals=goals,
                                 addressable_roots=[Address.parse(spec) for spec in root_specs])
    execution_graph = self.scheduler.execution_graph(build_request)

    plans = list(execution_graph.walk())
    self.assertEqual(1, len(plans))
    self.assertEqual((Classpath,
                      Plan(func_or_task_type=IvyResolve, subjects=jars, jars=list(jars))),
                     self.extract_product_type_and_plan(plans[0]))

  def test_resolve(self):
    self.assert_resolve_only(goals=['resolve'],
                             root_specs=['3rdparty/jvm:guava'],
                             jars=[self.guava])

  def test_compile_only_3rdaprty(self):
    self.assert_resolve_only(goals=['compile'],
                             root_specs=['3rdparty/jvm:guava'],
                             jars=[self.guava])

  def test_gen_noop(self):
    # TODO(John Sirois): Ask around - is this OK?
    # This is different than today.  There is a gen'able target reachable from the java target, but
    # the scheduler 'pull-seeding' has ApacheThriftPlanner stopping short since the subject it's
    # handed is not thrift.
    build_request = BuildRequest(goals=['gen'], addressable_roots=[self.java.address])
    execution_graph = self.scheduler.execution_graph(build_request)

    plans = list(execution_graph.walk())
    self.assertEqual(0, len(plans))

  def test_gen(self):
    build_request = BuildRequest(goals=['gen'], addressable_roots=[self.thrift.address])
    execution_graph = self.scheduler.execution_graph(build_request)

    plans = list(execution_graph.walk())
    self.assertEqual(1, len(plans))

    self.assertEqual((Sources.of('.java'),
                      Plan(func_or_task_type=gen_apache_thrift,
                           subjects=[self.thrift],
                           strict=True,
                           rev='0.9.2',
                           gen='java',
                           sources=['src/thrift/codegen/simple/simple.thrift'])),
                     self.extract_product_type_and_plan(plans[0]))

  def test_codegen_simple(self):
    build_request = BuildRequest(goals=['compile'], addressable_roots=[self.java.address])
    execution_graph = self.scheduler.execution_graph(build_request)

    plans = list(execution_graph.walk())
    self.assertEqual(4, len(plans))

    thrift_jars = [Jar(org='org.apache.thrift', name='libthrift', rev='0.9.2'),
                   Jar(org='commons-lang', name='commons-lang', rev='2.5'),
                   self.graph.resolve(Address.parse('src/thrift:slf4j-api'))]

    jars = [self.guava] + thrift_jars

    # Independent leaves 1st
    self.assertEqual({(Sources.of('.java'),
                       Plan(func_or_task_type=gen_apache_thrift,
                            subjects=[self.thrift],
                            strict=True,
                            rev='0.9.2',
                            gen='java',
                            sources=['src/thrift/codegen/simple/simple.thrift'])),
                      (Classpath, Plan(func_or_task_type=IvyResolve, subjects=jars, jars=jars))},
                     set(self.extract_product_type_and_plan(p) for p in plans[0:2]))

    # The rest is linked.
    self.assertEqual((Classpath,
                      Plan(func_or_task_type=Javac,
                           subjects=[self.thrift],
                           sources=Promise(Sources.of('.java'), self.thrift),
                           classpath=[Promise(Classpath, jar) for jar in thrift_jars])),
                     self.extract_product_type_and_plan(plans[2]))

    self.assertEqual((Classpath,
                      Plan(func_or_task_type=Javac,
                           subjects=[self.java],
                           sources=['src/java/codegen/simple/Simple.java'],
                           classpath=[Promise(Classpath, self.guava),
                                      Promise(Classpath, self.thrift)])),
                     self.extract_product_type_and_plan(plans[3]))

  @pytest.mark.xfail(raises=ConflictingProducersError)
  def test_multiple_classpath_entries(self):
    """Multiple Classpath products for a single subject currently cause a failure."""
    build_request = BuildRequest(goals=['compile'], addressable_roots=[self.java_multi.address])
    execution_graph = self.scheduler.execution_graph(build_request)
