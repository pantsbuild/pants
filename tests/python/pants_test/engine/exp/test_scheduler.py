# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import unittest

from pants.build_graph.address import Address
from pants.engine.exp.examples.planners import (ApacheThrift, Classpath, IvyResolve, Jar, JavacTask,
                                                Sources, setup_json_scheduler)
from pants.engine.exp.scheduler import BuildRequest, Plan, Promise


class SchedulerTest(unittest.TestCase):
  def setUp(self):
    build_root = os.path.join(os.path.dirname(__file__), 'examples', 'scheduler_inputs')
    self.graph, self.global_scheduler = setup_json_scheduler(build_root)

    self.guava = self.graph.resolve(Address.parse('3rdparty/jvm:guava'))
    self.thrift = self.graph.resolve(Address.parse('src/thrift/codegen/simple'))
    self.java = self.graph.resolve(Address.parse('src/java/codegen/simple'))

  def assert_resolve_only(self, goals, root_specs, jars):
    build_request = BuildRequest(goals=goals,
                                 addressable_roots=[Address.parse(spec) for spec in root_specs])
    execution_graph = self.global_scheduler.execution_graph(build_request)

    plans = list(execution_graph.walk())
    self.assertEqual(1, len(plans))
    self.assertEqual((Classpath, Plan(task_type=IvyResolve, subjects=jars, jars=list(jars))),
                     plans[0])

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
    execution_graph = self.global_scheduler.execution_graph(build_request)

    plans = list(execution_graph.walk())
    self.assertEqual(0, len(plans))

  def test_gen(self):
    build_request = BuildRequest(goals=['gen'], addressable_roots=[self.thrift.address])
    execution_graph = self.global_scheduler.execution_graph(build_request)

    plans = list(execution_graph.walk())
    self.assertEqual(1, len(plans))

    self.assertEqual((Sources.of('.java'),
                      Plan(task_type=ApacheThrift,
                           subjects=[self.thrift],
                           strict=True,
                           rev='0.9.2',
                           gen='java',
                           sources=['src/thrift/codegen/simple/simple.thrift'])),
                     plans[0])

  def test_codegen_simple(self):
    build_request = BuildRequest(goals=['compile'], addressable_roots=[self.java.address])
    execution_graph = self.global_scheduler.execution_graph(build_request)

    plans = list(execution_graph.walk())
    self.assertEqual(4, len(plans))

    thrift_jars = [Jar(org='org.apache.thrift', name='libthrift', rev='0.9.2'),
                   Jar(org='commons-lang', name='commons-lang', rev='2.5'),
                   Jar(org='org.slf4j', name='slf4j-api', rev='1.6.1')]

    jars = [self.guava] + thrift_jars

    # Independent leaves 1st
    self.assertEqual({(Sources.of('.java'),
                       Plan(task_type=ApacheThrift,
                            subjects=[self.thrift],
                            strict=True,
                            rev='0.9.2',
                            gen='java',
                            sources=['src/thrift/codegen/simple/simple.thrift'])),
                      (Classpath, Plan(task_type=IvyResolve, subjects=jars, jars=jars))},
                     set(plans[0:2]))

    # The rest is linked.
    self.assertEqual((Classpath,
                      Plan(task_type=JavacTask,
                           subjects=[self.thrift],
                           sources=Promise(Sources.of('.java'), self.thrift),
                           classpath=[Promise(Classpath, jar) for jar in thrift_jars])),
                     plans[2])

    self.assertEqual((Classpath,
                      Plan(task_type=JavacTask,
                           subjects=[self.java],
                           sources=['src/java/codegen/simple/Simple.java'],
                           classpath=[Promise(Classpath, self.guava),
                                      Promise(Classpath, self.thrift)])),
                     plans[3])
